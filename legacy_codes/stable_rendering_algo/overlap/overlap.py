import time
import tqdm
import torch
import torch.nn.functional as F

from typing import List, Sequence

from diffusers import AutoencoderKL
from .algorithms import OverlapAlgorithm
from .overlap_scheduler import Scheduler
from .utils import calculate_overlap_rate
from ..data_classes import CorrespondenceMap, Rectangle
from common_utils.global_utils import is_engine_looping
from common_utils.debug_utils import DefaultLogger as logu



class Overlap:
    r"""
    Parent class for all overlapping algorithms used in multi_frame_stable_diffusion.py
    """

    def __init__(
        self,
        alpha_scheduler: 'Scheduler',
        kernel_radius_scheduler: Scheduler,
        algorithm: OverlapAlgorithm,
        verbose: bool = True
    ):
        """
        Create a functional object instance of Overlap class
        :param alpha: Ratio of computed overlap values to original latent frame values in function return
            when set to 1, the returned overlap latent sequence is composed of purely computed values
            when set to 0, the returned overlap latent sequence is composed of all original frame values
        :param torch_dtype: Data type of function return
        :param verbose: Enable runtime messages
        """
        self._verbose = verbose
        self.algorithm = algorithm

        # Module for scheduling alpha, no need to be private
        self.alpha_scheduler = alpha_scheduler
        self.kernel_radius_scheduler = kernel_radius_scheduler

    @property
    def verbose(self):
        return self._verbose

    @verbose.setter
    def verbose(self, value: bool):
        self._verbose = value

    @staticmethod
    def calculate_overlap_rate(ovlp_seq: List[torch.Tensor], threshold: float = 0.0):
        """
        Debug function to calculate the overlap rate of a sequence of frames.
        :param ovlp_seq: A list of overlapped frames. Note that this should haven't been overlapped with the original frames.
        """
        return calculate_overlap_rate(ovlp_seq, threshold)
    
    def _get_extended_traces(self,
                             kernel_radius: int,
                             frame_index_trace: Sequence[int], 
                             x_position_trace: Sequence[int], 
                             y_position_trace: Sequence[int],
                             max_x: int = 512,
                             max_y: int = 512):
        extended_frame_index_trace, extended_y_position_trace, extended_x_position_trace = \
            list(frame_index_trace), list(y_position_trace), list(x_position_trace)

        for idx, (y_pos, x_pos) in enumerate(zip(extended_y_position_trace, extended_x_position_trace)):
            y_positions, x_positions = [], []
            for i in range(-kernel_radius, kernel_radius + 1):
                y_positions.append(min(max(y_pos + i, 0), max_y-1))
                x_positions.append(min(max(x_pos + i, 0), max_x-1))
            extended_y_position_trace[idx] = y_positions
            extended_x_position_trace[idx] = x_positions
            extended_frame_index_trace[idx] = [frame_index_trace[idx]] * len(y_positions) 
        
        return extended_frame_index_trace, extended_y_position_trace, extended_x_position_trace

    @torch.no_grad()
    def __call__(
        self,
        frame_seq: List[torch.Tensor],
        corr_map: CorrespondenceMap,
        step: int = None,
        timestep: int = None,
        apply_corr_map_decay: bool = False,
        **kwargs,
    ):
        assert frame_seq[0].shape[2:] == (corr_map.height, corr_map.width), f"frame shape {frame_seq[0].shape[2:]} does not match corr_map shape {(corr_map.height, corr_map.width)}"

        num_frames = len(frame_seq)
        batch_size, channels, frame_h, frame_w = frame_seq[0].shape
        frame_seq_stack = torch.stack(frame_seq, dim=0)  # [T, B, C, H, W] # Usually [16, 1, 4, 512, 512]
        frame_seq_stack_copy = frame_seq_stack.detach()
        # mask_seq = torch.zeros((num_frames, batch_size, channels, frame_h, frame_w), dtype=torch.uint8, device=frame_seq[0].device)  # [T, 1, H, W]

        alpha = self.alpha_scheduler(step, timestep)
        kernel_radius = int(self.kernel_radius_scheduler(step, timestep))

        # rectangle = Rectangle((170, 168), (351, 297))
        # rectangle = Rectangle((170, 168), (351, 220))
        # rectangle = Rectangle((0, 0), (frame_w, frame_h))
        # at_frame = 0

        if not is_engine_looping():
            logu.success(f"Scheduler: alpha: {alpha} | kernel_radius: {kernel_radius} | timestep: {timestep:.2f}")
        
        len_1_vertex_count = index_decay_count = avg_trace_length = 0

        tic = time.time()

        if not is_engine_looping():
            progress_slice = len(corr_map) // 100
            pbar = tqdm.tqdm(total=100, desc='Overlap', unit='%', leave=False)
        
        for v_i, v_info in enumerate(corr_map.Map.values()):
            if not is_engine_looping():
                pbar.update(1) if v_i % progress_slice == 0 else ...

            if len(v_info) == 1:
                # no value changes when vertex appear once only
                len_1_vertex_count += 1
                avg_trace_length += 1
                continue
            # Extract traces from correspondence map
            position_trace, frame_index_trace = zip(*v_info)
            y_position_trace, x_position_trace = zip(*position_trace) # h, w
            extended_frame_index_trace, extended_y_position_trace, extended_x_position_trace = \
                self._get_extended_traces(kernel_radius, frame_index_trace, x_position_trace, y_position_trace,
                                            max_x=frame_w, max_y=frame_h)
            avg_trace_length += len(frame_index_trace)
                
            latent_seq = frame_seq_stack[frame_index_trace, :, :, y_position_trace, x_position_trace]
            average_pool_nearby_pixels_latent_seq = frame_seq_stack[
                extended_frame_index_trace, :, :, extended_y_position_trace, extended_x_position_trace].mean(dim=1)

            overlapped_seq = self.algorithm.overlap(
                average_pool_nearby_pixels_latent_seq, frame_index_trace, x_position_trace, y_position_trace, **kwargs)
            
            del average_pool_nearby_pixels_latent_seq
            
            frame_seq_stack_copy[frame_index_trace, :, :, y_position_trace, x_position_trace] = alpha * overlapped_seq + (1 - alpha) * latent_seq
            del overlapped_seq, latent_seq
            
        toc = time.time()
        logu.success(f"Overlap cost: {toc - tic:.2f}s in total | {(toc-tic)/num_frames:.2f}s per frame") if self.verbose else ...
        logu.success(f"Vertex appeared once: {len_1_vertex_count * 100 / max(len(corr_map), 1) :.2f}% | Average trace length: {avg_trace_length / max(len(corr_map), 1) :.2f} | Index decayed: {index_decay_count}")

        return frame_seq_stack_copy


class ResizeOverlap(Overlap):
    def __init__(
        self,
        alpha_scheduler: Scheduler,
        kernel_radius_scheduler: Scheduler,
        algorithm: OverlapAlgorithm,
        verbose: bool = True,
        interpolate_mode: str = 'nearest'
    ):
        super().__init__(
            alpha_scheduler=alpha_scheduler,
            kernel_radius_scheduler=kernel_radius_scheduler,
            algorithm=algorithm,
            verbose=verbose,
        )
        self._interpolate_mode = interpolate_mode

    @property
    def interpolate_mode(self):
        return self._interpolate_mode

    @interpolate_mode.setter
    def interpolate_mode(self, value: str):
        self._interpolate_mode = value

    def __call__(
        self,
        frame_seq: List[torch.Tensor],
        corr_map: CorrespondenceMap,
        step: int = None,
        timestep: int = None,
        **kwargs
    ):
        """
        Do overlapping with resizing the latents list to the size of the correspondence map.
        :param latents_seq: A list of frame latents. Each element is a tensor of shape [B, C, H, W].
        :param corr_map: correspondence map
        :param step: current inference step
        :param timestep: current inference timestep
        :return: A list of overlapped frame latents.
        """
        print("Calling resized overlap")
        print("Received frame_seq with length", len(frame_seq))
        print("Received frame_seq with shape ", frame_seq[0].shape)
        alpha = self.alpha_scheduler(step, timestep)
        if alpha == 0:
            return frame_seq
        num_frames = len(frame_seq)
        screen_w, screen_h = corr_map.size
        frame_h, frame_w = frame_seq[0].shape[-2:]
        align_corners = False if self.interpolate_mode in ['linear', 'bilinear', 'bicubic', 'trilinear'] else None

        ovlp_seq = [F.interpolate(latents, size=(screen_h, screen_w), mode=self.interpolate_mode, align_corners=align_corners) for latents in frame_seq]
        print("resized as ", ovlp_seq[0].shape)
        ovlp_seq = super().__call__(
            ovlp_seq,
            corr_map=corr_map,
            step=step,
            timestep=timestep,
            **kwargs
        )
        ovlp_seq = [F.interpolate(latents, size=(frame_h, frame_w), mode=self.interpolate_mode, align_corners=align_corners) for latents in ovlp_seq]

        logu.debug(f"Resize scale factor: {screen_h / frame_h:.2f} | Overlap ratio: {100 * self.calculate_overlap_rate(ovlp_seq, threshold=0):.2f}%")

        # Overlap with original
        ovlp_seq = [torch.where(ovlp_seq[i] != 0, ovlp_seq[i], frame_seq[i]) for i in range(num_frames)]
        return ovlp_seq


class VAEOverlap(Overlap):
    def __init__(
        self,
        vae: AutoencoderKL,
        generator: torch.Generator,
        algorithm: OverlapAlgorithm,
        alpha_scheduler: Scheduler,
        corr_map_decay_scheduler: Scheduler,
        kernel_radius_scheduler: Scheduler,
        verbose: bool = True,
    ):
        super().__init__(
            alpha_scheduler=alpha_scheduler,
            corr_map_decay_scheduler=corr_map_decay_scheduler,
            kernel_radius_scheduler=kernel_radius_scheduler,
            algorithm=algorithm,
            verbose=verbose,
        )
        self._vae = vae
        self._generator = generator

    @property
    def vae(self):
        return self._vae

    @property
    def generator(self):
        return self._generator

    def _encode(self, image):
        latent_dist = self.vae.encode(image).latent_dist
        latents = latent_dist.sample(generator=self.generator)
        latents = self.vae.config.scaling_factor * latents
        return latents

    def _decode(self, latents):
        latents = 1 / self.vae.config.scaling_factor * latents
        image = self.vae.decode(latents).sample
        return image

    # TODO: Optimize this function
    def __call__(
        self,
        frame_seq: List[torch.Tensor],
        corr_map: CorrespondenceMap,
        step: int = None,
        timestep: int = None,
        **kwargs,
    ):
        """
        Do overlapping with VAE decode/encode a latents to pixel space.
        :param latents_seq: A sequence of latents.
        :param corr_map: A correspondence map.
        :param step: The current step.
        :param timestep: The current timestep.
        :return: A sequence of overlapped latents.
        """

        num_frames = len(frame_seq)
        screen_w, screen_h = corr_map.size
        frame_h, frame_w = frame_seq[0].shape[-2:]

        #! IMPORTANT:
        #! (1) After VAE encoding, 0's in the latents will not be 0's anymore
        #! (2) After VAE decoding, the number of channels will change from 4 to 3. Encoding will do reverse.
        #! (3) Do not overlap original in pixel space and then encode to latent space. This will destroy generation.
        # TODO: However, if we can overlap original at latent space directly, then the destruction might be much less.

        pix_seq = [self._decode(latents) for latents in frame_seq]
        ovlp_seq = super().__call__(
            pix_seq,
            corr_map=corr_map,
            step=step,
            timestep=timestep,
            **kwargs,
        )
        ovlp_seq = [torch.where(ovlp_seq[i] != 0, ovlp_seq[i], pix_seq[i]) for i in range(num_frames)]  # Overlap with original
        ovlp_seq = [self._encode(ovlp_img) for ovlp_img in ovlp_seq]

        # ovlp_seq = [torch.where(abs(ovlp_seq[i] - latents_seq[i]) > 0.1, ovlp_seq[i], latents_seq[i]) for i in range(num_frames)]

        return ovlp_seq