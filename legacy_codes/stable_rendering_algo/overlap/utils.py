import os
from typing import List, Literal, Tuple

import cv2
import numpy as np
from PIL import Image

from diffusers.utils import PIL_INTERPOLATION
from torchvision.transforms import ToTensor
import torch.nn.functional as F
import torch


def calculate_overlap_rate(ovlp_seq: List[torch.Tensor], threshold: float = 0.0):
    """
    Debug function to calculate the overlap rate of a sequence of frames.
    :param ovlp_seq: A list of overlapped frames. Note that this should haven't been overlapped with the original frames.
    """
    num_zeros = torch.sum(torch.stack([torch.sum(abs(latents - threshold) <= 0) for latents in ovlp_seq]))
    num_nonzeros = torch.sum(torch.stack([torch.sum(abs(latents - threshold) > 0) for latents in ovlp_seq]))
    return num_nonzeros / (num_nonzeros + num_zeros)


def value_interpolation(
        x: float,
        start: float,
        end: float, 
        power: float = 1.0,
        interpolate_function: Literal["constant", "linear", "cosine", "exponential"] = "constant"):
    r"""
    Interpolate value from `start` to `end` with `interpolate_function`, controlled by `x`
    :param x: float between 0 to 1 to control interpolation
    :param start: start value
    :param end: end value
    :param power: control the curviness of interpolation, 
        A `power` greater than 1 will make the interpolation slower at the start and faster at the end;
        while a `power` less than 1 will make the interpolation faster at the start and slower at the end.
        the value should be non-negative
    :param interpolate_function: function used for interpolation
    """ 
    assert x >= 0 and x <= 1
    assert power >= 0

    if interpolate_function == "constant":
        return start
    elif interpolate_function == "linear":
        return start + (end - start) * x ** power
    elif interpolate_function == "cosine":
        return start + (end - start) * (1 + torch.cos(x ** power * torch.pi)) / 2
    elif interpolate_function == "exponential":
        return start * (end / start) ** (x ** power)
    else:
        raise NotImplementedError


def build_view_normal_map(normal_images: List[Image.Image], view_vector: torch.Tensor, dtype=torch.float32) -> torch.Tensor:
    r"""
    Builds a view normal map by computing the dot product between normal images and a view vector.

    Args:
        normal_images (List[Image.Image]): A list of normal images represented as PIL Image objects.
        view_vector (torch.Tensor): View vector used for computing the dot product. Shape: [1, 3].
        dtype (torch.dtype, optional): Data type of the tensors. Default: torch.float32.

    Returns:
        torch.Tensor: View normal map tensor. Shape: [T, H, W, C].

    Raises:
        TypeError: If the input normal_images is not a list or if the elements in the list are not PIL Image objects.

    Notes:
        The input normal_images are converted to torch Tensors using torchvision.transforms.ToTensor() and reshaped to 
        have shape [T, H, W, C], where T is the number of normal images, H is the height, W is the width, and C is the number
        of channels. The view_vector is normalized using L2 normalization and expanded to match the shape of normal_map.
        The dot product between normal_map and view_vector is computed using torch.einsum() and the absolute value is taken
        to ensure positive values in the resulting view_normal_map.

    Example:
        import torch
        from PIL import Image
        from torchvision import transforms

        normal_images = [Image.open('normal1.png'), Image.open('normal2.png')]
        view_vector = torch.tensor([[0, 0, 1]], dtype=torch.float32)

        # Convert normal_images to view normal map
        view_normal_map = build_view_normal_map(normal_images, view_vector)
    """
    # Check input types
    if not isinstance(normal_images, list):
        raise TypeError("normal_images must be a list of PIL Image objects.")
    if not all(isinstance(image, Image.Image) for image in normal_images):
        raise TypeError("normal_images must contain PIL Image objects.")
    
    normal_map = [ToTensor()(normal_image).permute(1, 2, 0) for normal_image in normal_images]
    normal_map = torch.stack(normal_map, dim=0).unsqueeze(3)    # [T, H, W, 1, C]

    view_vector = F.normalize(view_vector.to(dtype), p=2, dim=0).expand_as(normal_map)   # [T, H, W, 1, C]

    # Compute dot product between normal_map and view_vector
    view_normal_map = torch.abs(torch.einsum("thwdc, thwdc -> thwd", normal_map, view_vector)) # [T, H, W, 1]
    return view_normal_map


def generate_canny_images(
    images_path: str,
    output_path: str,
    canny_lower_threshold: int = 100,
    canny_upper_threshold: int = 200
):
    assert os.path.exists(images_path)
    image_file_extensions = (".jpg", '.jpeg', '.png')
    
    os.makedirs(output_path, exist_ok=True)
    files = os.listdir(images_path)

    for file in files:
        if file.endswith(image_file_extensions):
            image = cv2.imread(os.path.join(images_path, file))
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, canny_lower_threshold, canny_upper_threshold)
            cv2.imwrite(os.path.join(output_path, "canny_" + file), edges)


def draw_rectangle(image: np.ndarray,
                   top_left: Tuple[int, int],
                   bottom_right: Tuple[int, int],
                   color: Tuple[int, int, int], 
                   thickness: int) -> np.ndarray:
    """Wrapper for the cv2 draw rectangle function"""
    return cv2.rectangle(image, top_left, bottom_right, color=color, thickness=thickness)

def pil_to_tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

if __name__ == "__main__":
    def gen_canny_helper():
        root = "/mnt/disk1/Stable-Renderer/output/runtime_map/2024-03-14_0"
        generate_canny_images(
            images_path=os.path.join(root, 'color'),
            output_path=os.path.join(root, 'canny'),
        )
    def draw_and_show_rectangle():
        image_path = "/research/d1/spc/ckwong1/document/Stable-Renderer/output/gif/2024-02-04_02-47_output_0.gif"
        images = Image.open(image_path)

        static_image = np.asarray(images.convert('RGB'))

        drawn_array = draw_rectangle(static_image, (170, 168), (351, 220), (0, 0, 255), 2)

        drawn_image = Image.fromarray(drawn_array)
        drawn_image.save(os.path.join(os.path.dirname(image_path), os.path.basename(image_path).replace(".gif", ".png")))
    gen_canny_helper()
