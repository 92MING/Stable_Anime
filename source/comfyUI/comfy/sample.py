import torch
import math
import numpy as np

from typing import List, Tuple, Optional, Callable, Any, TYPE_CHECKING
from common_utils.debug_utils import ComfyUILogger
import comfy.model_management
import comfy.model_patcher
import comfy.samplers
import comfy.conds
import comfy.utils

if TYPE_CHECKING:
    from comfyUI.types import CONDITIONING as Conditioning, ConvertedCondition
    from comfy.model_base import BaseModel
    
SelfDefinedModelPatcher = Any

def prepare_noise(latent_image: torch.Tensor, seed: int|None, noise_indexes=None):
    """
    creates random noise given a latent image and a seed.
    optional arg skip can be used to skip and discard x number of noise generations for a given seed
    """
    if seed is None:
        seed = int(torch.randint(0, 2**32, (1,)).item())
    generator = torch.manual_seed(seed)
    if noise_indexes is None:
        return torch.randn(latent_image.size(), dtype=latent_image.dtype, layout=latent_image.layout, generator=generator, device="cpu")
    
    unique_inds, inverse = np.unique(noise_indexes, return_inverse=True)
    noises = []
    for i in range(unique_inds[-1]+1):
        noise = torch.randn([1] + list(latent_image.size())[1:], dtype=latent_image.dtype, layout=latent_image.layout, generator=generator, device="cpu")
        if i in unique_inds:
            noises.append(noise)
    noises = [noises[i] for i in inverse]
    noises = torch.cat(noises, axis=0)  # type: ignore
    return noises

def prepare_mask(noise_mask, shape, device):
    """ensures noise mask is of proper dimensions"""
    noise_mask = torch.nn.functional.interpolate(noise_mask.reshape((-1, 1, noise_mask.shape[-2], noise_mask.shape[-1])), size=(shape[2], shape[3]), mode="bilinear")
    noise_mask = torch.cat([noise_mask] * shape[1], dim=1)
    noise_mask = comfy.utils.repeat_to_batch_size(noise_mask, shape[0])
    noise_mask = noise_mask.to(device)
    return noise_mask

def get_models_from_cond(cond: "Conditioning", model_type):
    models = []
    for c in cond:
        if model_type in c:
            models += [c[model_type]]
    return models

def convert_cond(cond: "Conditioning", extra_params: dict|None=None) -> list["ConvertedCondition"]:
    """
    Transforms the conditioning to a format that can be used by the model.

    Original format:
    [
        [cond_tensor_a, {"some_output_a": Any, ...}],
        [cond_tensor_b, {"some_output_b": Any, ...}], 
        ...
    ] 
    
    Transformed format:
    [
        {
            "some_output_a": Any, 
            "cross_attn": cond_tensor_a,
            "model_conds": {
                "c_crossattn": comfy.conds.CONDCrossAttn(cond_tensor_a)
            }
            ...extra_params
        },
        ...
    ]
    
    Args:
        cond: The original conditioning.
        extra_params: Extra parameters to be added to the transformed conditioning.
    """
    out = []
    for c in cond:
        temp = c[1].copy()
        model_conds = temp.get("model_conds", {})
        
        if c[0] is not None:
            model_conds["c_crossattn"] = comfy.conds.CONDCrossAttn(c[0]) #TODO: remove
            temp["cross_attn"] = c[0]
            
        temp["model_conds"] = model_conds
        temp.update(extra_params or {})
        out.append(temp)
        
    from comfyUI.types import ConvertedCondition
    return [ConvertedCondition(o) for o in out]

def get_additional_models(positive, negative, dtype):
    """loads additional models in positive and negative conditioning"""
    control_nets = set(get_models_from_cond(positive, "control") + get_models_from_cond(negative, "control"))

    inference_memory = 0
    control_models = []
    for m in control_nets:
        control_models += m.get_models()
        inference_memory += m.inference_memory_requirements(dtype)

    gligen = get_models_from_cond(positive, "gligen") + get_models_from_cond(negative, "gligen")
    gligen = [x[1] for x in gligen]
    models = control_models + gligen
    return models, inference_memory

def cleanup_additional_models(models):
    """cleanup additional models that were loaded"""
    for m in models:
        if hasattr(m, 'cleanup'):
            m.cleanup()

def prepare_sampling(model: comfy.model_patcher.ModelPatcher,
                     noise_shape: torch.Size,
                     positive: "Conditioning",
                     negative: "Conditioning",
                     noise_mask: Optional[torch.Tensor],
    ) -> Tuple[
        "BaseModel",
        list["ConvertedCondition"],
        list["ConvertedCondition"],
        Optional[torch.Tensor],
        List[comfy.model_patcher.ModelPatcher | SelfDefinedModelPatcher]
    ]:
    device = model.load_device
    converted_positive = convert_cond(positive)
    converted_negative = convert_cond(negative)

    if noise_mask is not None:
        noise_mask = prepare_mask(noise_mask, noise_shape, device)

    real_model = None
    models, inference_memory = get_additional_models(converted_positive, converted_negative, model.model_dtype())
    comfy.model_management.load_models_gpu([model] + models, model.memory_required([noise_shape[0] * 2] + list(noise_shape[1:])) + inference_memory)
    real_model = model.model

    return real_model, converted_positive, converted_negative, noise_mask, models


def sample(model: comfy.model_patcher.ModelPatcher,
           noise: torch.Tensor,
           steps: int,
           cfg: float,
           sampler_name: str,
           scheduler: str,
           positive: "Conditioning",
           negative: "Conditioning",
           latent_image: torch.Tensor,
           denoise: float = 1.0,
           disable_noise: bool = False,
           start_step: int|None = None,
           last_step: int|None = None,
           force_full_denoise: bool = False,
           noise_mask: torch.Tensor|None = None,
           sigmas: torch.Tensor|None = None,
           callbacks: List[Callable] = [],
           disable_pbar: bool = False,
           seed: int|None = None,
           **kwargs) -> torch.Tensor:
    if "callback" in kwargs:
        ComfyUILogger.warn("Warning: 'callback' is deprecated, use 'callbacks' instead")
        legacy_callback = kwargs.pop("callback")
        callbacks.append(legacy_callback)

    real_model, positive_copy, negative_copy, noise_mask, models = prepare_sampling(model, noise.shape, positive, negative, noise_mask)

    noise = noise.to(model.load_device)
    latent_image = latent_image.to(model.load_device)

    ksampler = comfy.samplers.KSampler(real_model, 
                                       steps=steps, 
                                       device=model.load_device, 
                                       sampler=sampler_name,    # sampler method, e.g. "euler" 
                                       scheduler=scheduler, 
                                       denoise=denoise, 
                                       model_options=model.model_options)

    samples = ksampler.sample(noise, 
                              positive_copy, 
                              negative_copy, 
                              cfg=cfg, 
                              latent_image=latent_image, 
                              start_step=start_step, 
                              last_step=last_step, 
                              force_full_denoise=force_full_denoise, 
                              denoise_mask=noise_mask, 
                              sigmas=sigmas, 
                              callbacks=callbacks, 
                              disable_pbar=disable_pbar, 
                              seed=seed,
                              **kwargs)
    samples = samples.to(comfy.model_management.intermediate_device())

    cleanup_additional_models(models)
    cleanup_additional_models(set(get_models_from_cond(positive_copy, "control") + get_models_from_cond(negative_copy, "control")))
    return samples

def sample_custom(model, noise, cfg, sampler, sigmas, positive, negative, latent_image, noise_mask=None, callback=None, disable_pbar=False, seed=None):
    real_model, positive_copy, negative_copy, noise_mask, models = prepare_sampling(model, noise.shape, positive, negative, noise_mask)
    noise = noise.to(model.load_device)
    latent_image = latent_image.to(model.load_device)
    sigmas = sigmas.to(model.load_device)

    samples = comfy.samplers.sample(real_model, noise, positive_copy, negative_copy, cfg, model.load_device, sampler, sigmas, model_options=model.model_options, latent_image=latent_image, denoise_mask=noise_mask, callbacks=callback, disable_pbar=disable_pbar, seed=seed)
    samples = samples.to(comfy.model_management.intermediate_device())
    cleanup_additional_models(models)
    cleanup_additional_models(set(get_models_from_cond(positive_copy, "control") + get_models_from_cond(negative_copy, "control")))
    return samples

