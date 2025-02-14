import re
import os
import math
import json
import warnings
from abc import ABC, abstractmethod, ABCMeta

import torch
import numpy as np
import einops
from torchvision.io import read_image

from pydantic import BaseModel


class ViewPoint(BaseModel):
    radius: float
    phi: float  # inclination
    theta: float  # azimuth

    def to_tensor(self):
        return torch.tensor([self.radius, self.phi, self.theta], dtype=torch.float32)
    
    @classmethod
    def from_tensor(cls, tensor: torch.Tensor):
        return cls(radius=tensor[0].item(), phi=tensor[1].item(), theta=tensor[2].item())

    @classmethod
    def from_cartesian(cls, x: float, y: float, z: float):
        radius = math.sqrt(x**2 + y**2 + z**2)
        theta = math.atan2(z, x)
        phi = math.acos(y / radius)
        return cls(radius=radius, phi=phi, theta=theta)

    def to_cartesian(self):
        x = self.radius * math.sin(self.phi) * math.cos(self.theta)
        y = self.radius * math.cos(self.phi)
        z = self.radius * math.sin(self.phi) * math.sin(self.theta)
        return x, y, z

    def __str__(self):
        return f'{self.__class__.__name__}(radius: {self.radius}, phi: {self.phi}, theta: {self.theta})'

    def __repr__(self):
        return self.__str__()


class SphereCache(ABC):
    def __init__(self, num_possible_views: int = 1):
        self._num_possible_views = num_possible_views
        self._init_view_normal_thresholds()

    def _init_view_normal_thresholds(self):
        view_normal_thresholds = [[0, 0, 1]]
        LEFT = torch.tensor([1, 0, 0])
        RIGHT = torch.tensor([-1, 0, 0])
        UP = torch.tensor([0, 1, 0])
        DOWN = torch.tensor([0, -1, 0])


        i_th_inner_grid_perimeter = None
        for i in range(1, self.sqrt_num_possible_views // 2 + 1 + 1):
            phi = i * math.pi / 2 / (self.sqrt_num_possible_views // 2 + 1)
            if math.isclose(phi, math.pi / 2, rel_tol=1e-5):
                view_normal_thresholds.append([0, 0, 1])
            else:
                if i == 0:
                    i_th_inner_grid_perimeter = 1
                elif i == 1:
                    i_th_inner_grid_perimeter = 8
                else:
                    i_th_inner_grid_perimeter = (i_th_inner_grid_perimeter + 4) // 4 * 4 + 4
                for j in range(i_th_inner_grid_perimeter):
                    theta = j * 2 * math.pi / (i_th_inner_grid_perimeter)
                    x, y, z = [round(n, 5) for n in self.get_cartesian_coordinates(1, theta, phi)]
                    view_normal_thresholds.append([x, y, z])
        print(view_normal_thresholds)
        print(len(view_normal_thresholds))




        view_normal_thresholds = torch.nn.functional.normalize(view_normal_thresholds, dim=-1)
        self._view_normal_thresholds = einops.rearrange(view_normal_thresholds, 'h w c -> h w 1 c')

    @property
    def num_possible_views(self) -> int:
        return self._num_possible_views
    
    @property
    def sqrt_num_possible_views(self) -> int:
        return int(math.sqrt(self.num_possible_views))
    
    @property
    def view_normal_thresholds(self) -> torch.Tensor:
            """
            Returns the view normal thresholds.
            Assuming num_possible_views = 3, the view normal thresholds are organized as:
            [
                [top_left, top_center, top_right],
                [middle_left, middle_center, middle_right],
                [bottom_left, bottom_center, bottom_right]
            ]

            Returns:
                A torch.Tensor representing the view normal thresholds.
            """
            return self._view_normal_thresholds
    
    @abstractmethod
    def get_view(self, view_point: torch.Tensor) -> torch.Tensor:
        pass

    @abstractmethod
    def store_view(
            self,
            view_point: torch.Tensor,
            view: torch.Tensor,
            **kwargs
        ):
        pass

    @abstractmethod
    def clear():
        pass

    @staticmethod
    def get_cartesian_coordinates(radius: float,
                                  theta: float,
                                  phi: float,
        ) -> tuple[float, float, float]:
        x = radius * math.sin(phi) * math.cos(theta)
        y = radius * math.cos(phi)
        z = radius * math.sin(phi) * math.sin(theta)
        return x, y, z
    
    @staticmethod
    def get_spherical_coordinates(x: float,
                                  y: float,
                                  z: float
        ) -> tuple[float, float, float]:
        radius = math.sqrt(x**2 + y**2 + z**2)
        theta = math.atan2(z, x)
        phi = math.acos(y / radius)
        return radius, theta, phi

    
class SimpleSphereCache(SphereCache):
    def __init__(self,
                 radius: float,
                 num_latitude_lines: int,
                 num_longitude_lines: int,
                 num_possible_views: int = 1):
        """
        Initialize a SimpleSphereCache object.

        Args:
            radius (int): The radius of the sphere.
            num_latitude_lines (int): The number of latitude (vertical) lines.
            num_longtitude_lines (int): The number of longtitude (horizontal) lines.
        """
        super().__init__(num_possible_views=num_possible_views)
        assert math.sqrt(num_possible_views) % 1 == 0, "num_possible_views must be a perfect square"
        self.radius = radius
        self.num_latitude_lines = num_latitude_lines
        self.num_longitude_lines = num_longitude_lines

        self._cache = {}
        self._init_cache()
        warnings.warn("SimpleSphereCache is not implemented yet. Please implement the get_view and store_view methods.")
    


    def _init_cache(self):
        latitude_step = math.pi / self.num_latitude_lines
        longitude_step = 2 * math.pi / self.num_longitude_lines
        cache_value_shape = (self.sqrt_num_possible_views, self.sqrt_num_possible_views, 3)
        
        for latitude in range(self.num_latitude_lines):
            for longitude in range(self.num_longitude_lines):
                theta = longitude * longitude_step
                phi = latitude * latitude_step

                x, y, z = self.get_cartesian_coordinates(theta, phi, self.radius)

                # cache[(x, y, z)] = [view1_color, view2_color, ...]
                # view1_color = [view1_color_x, view1_color_y, view1_color_z]
                self._cache[(x, y, z)] = torch.zeros(size=cache_value_shape)

    def get_view(self, view_point: torch.Tensor) -> torch.Tensor:
        raise NotImplementedError
        

    def store_view(
            self,
            view_point: torch.Tensor,
            view: torch.Tensor
        ):
        raise NotImplementedError


    def clear(self):
        self._cache = {}


class OpenGLSphereCache(SphereCache):
    def __init__(self,
                 num_possible_views: int = 1,
                 view_texture_size: tuple[int, int] = (512, 512)):
        """
        The spherical mesh structure will be handled by OpenGL

        Args:
            num_possible_views (int, optional):
                Number of possible views to one cache. It should be a square number. Defaults to 1.
        """
        assert math.sqrt(num_possible_views) % 1 == 0, "num_possible_views must be a perfect square"
        assert math.sqrt(num_possible_views) % 2 == 1, "sqrt of num_possible_views must be an odd number"
        super().__init__(num_possible_views)
        self._view_texture_size = view_texture_size
        self._possible_view_texture_maps = torch.zeros(size=(
            self.sqrt_num_possible_views,
            self.sqrt_num_possible_views,
            view_texture_size[0],
            view_texture_size[1],
            3
        ))
    
    @property
    def view_texture_size(self) -> tuple[int, int]:
        return self._view_texture_size
    
    @classmethod
    def from_numpy_files(cls,
                         num_possible_views: int,
                         view_texture_size: tuple[int, int],

                         sphere_view_id_files_dir: str,
                         sphere_view_normal_files_dir: str,
                         object_view_color_files_dir: str,
                         historical_positions_file: str,

                         num_views: int) -> 'OpenGLSphereCache':
        assert os.path.exists(sphere_view_id_files_dir), "sphere_view_id_files_dir does not exist"
        assert os.path.isdir(sphere_view_id_files_dir), "sphere_view_id_files_dir is not a directory"

        assert os.path.exists(sphere_view_normal_files_dir), "sphere_view_normal_files_dir does not exist"
        assert os.path.isdir(sphere_view_normal_files_dir), "sphere_view_normal_files_dir is not a directory"

        assert os.path.exists(object_view_color_files_dir), "object_view_color_files_dir does not exist"
        assert os.path.isdir(object_view_color_files_dir), "object_view_color_files_dir is not a directory"

        assert os.path.exists(historical_positions_file), "historical_positions_file does not exist"

        cache = OpenGLSphereCache(num_possible_views, view_texture_size)
        # Load and sort sphere view id file names
        sphere_view_id_files = sorted(
            [file for file in os.listdir(sphere_view_id_files_dir) if file.endswith(".npy")],
            key=lambda file: int(re.findall(r'\d+', file)[0])
        )
        # Load and sort sphere view normal file names
        sphere_view_normal_files = sorted(
            [file for file in os.listdir(sphere_view_normal_files_dir) if file.endswith(".png")],
            key=lambda file: int(re.findall(r'\d+', file)[0])
        )
        # Load and sort object view file names
        object_view_files = sorted(
            [file for file in os.listdir(object_view_color_files_dir) if file.endswith((".png", ".jpg"))],
            key=lambda file: int(re.findall(r'\d+', file)[0])
        )
        # Clamp the length of the files to the minimum of the two
        clamp_length = min(
            len(sphere_view_id_files),
            len(object_view_files),
            len(sphere_view_normal_files),
            num_views
        )
        # Load the sphere view data and object views
        sphere_view_ids = [
            np.load(os.path.join(sphere_view_id_files_dir, file))
            for file in sphere_view_id_files[:clamp_length]
        ]
        sphere_view_normals = [
            read_image(os.path.join(sphere_view_normal_files_dir, file))
            for file in sphere_view_normal_files[:clamp_length]
        ]
        object_views = [
            read_image(os.path.join(object_view_color_files_dir, file))
            for file in object_view_files[:clamp_length]
        ]
        # Load the historical positions
        with open(historical_positions_file, 'r') as f:
            historical_positions = json.load(f)
            for i in range(clamp_length):
                historical_positions[i] = ViewPoint(**historical_positions[i])
        # Store the views
        for historical_position, object_view, sphere_view_id, sphere_view_normal in zip(
            historical_positions, object_views, sphere_view_ids, sphere_view_normals):
            cache.store_view(historical_position, object_view, sphere_view_id, sphere_view_normal)

    def get_view(self,
                 view_point: torch.Tensor) -> torch.Tensor:
        raise NotImplementedError
    
    def store_view(self,
                   view_point: ViewPoint,
                   view: torch.Tensor,
                   id_map: np.ndarray,
                   normal_map: torch.Tensor):
        """Store a view from a view point

        Args:
            view_point (torch.Tensor):
                The view point of the object in spherical coordinates, (radius, theta, phi).
                Theta is the angle in xy plane, phi is the angle from z axis.
            view (torch.Tensor): _description_
            id_map (np.ndarray): The vertex id map of a view point
        """
        assert view.shape[0] == 3, f"view must be a 3D vector, got {view.shape}"
        assert view.shape[-2:] == normal_map.shape[-2:], f"View and normal map must have the same shape, got {view.shape} and {normal_map.shape}"

        h, w = view.shape[-2:]
        view_normal = torch.tensor([[0, 0, 1]], dtype=torch.float32)
        similarity = torch.einsum('ijkl,kl->ij', self.view_normal_thresholds, view_normal)
        print(similarity)
        exit()

        # non_zero_indices = torch.nonzero(torch.all(normal_map[0:3, :, :] != 0, dim=0))
        # for i, j in non_zero_indices:
        #     possible_view_horizontal_offset = 0
        #     possible_view_vertical_offset = 0
        #     closest_distance = float('inf')

        #     for h_index, horizontal_threshold in enumerate(self.view_normal_thresholds):
        #         for v_index, threshold in enumerate(horizontal_threshold):
        #             normal_vector = normal_map[0:3, i, j].to(torch.float32)
        #             if torch.dot(normal_vector, threshold) < closest_distance:
        #                 closest_distance = torch.dot(normal_vector, threshold)
        #                 possible_view_horizontal_offset = h_index
        #                 possible_view_vertical_offset = v_index

        #     texture_coordinates = id_map[i, j, 2:3]
        #     self._possible_view_texture_maps[
        #         possible_view_horizontal_offset,
        #         possible_view_vertical_offset,
        #         texture_coordinates[0],
        #         texture_coordinates[1]
        #     ] = view[:, i, j]

    def clear(self):
        self._possible_view_texture_maps = torch.zeros(size=(
            self.sqrt_num_possible_views,
            self.sqrt_num_possible_views,
            self.view_texture_size[0],
            self.view_texture_size[1],
            3
        ))



if __name__ == '__main__':
    sphere_id_files_dir =  "/mnt/disk2/Stable-Renderer-Previous/Stable-Renderer/resources/example-sphere-and-object-views/sphere/id"
    sphere_normal_files_dir = "/mnt/disk2/Stable-Renderer-Previous/Stable-Renderer/resources/example-sphere-and-object-views/sphere/normal"
    object_views_file_dir = "/mnt/disk2/Stable-Renderer-Previous/Stable-Renderer/resources/example-sphere-and-object-views/object"
    historical_positions_file = "/mnt/disk2/Stable-Renderer-Previous/Stable-Renderer/resources/example-sphere-and-object-views/historical_pos.json"

    cache = OpenGLSphereCache.from_numpy_files(
        25, (1024, 1024), sphere_id_files_dir, sphere_normal_files_dir, object_views_file_dir, historical_positions_file, 15
    )
