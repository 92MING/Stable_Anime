import os
from datetime import datetime
from typing import Optional
from pathlib import Path as _Path

_PathType = type(_Path())

class Path(_PathType):
    '''String comparable Path object.'''
    
    def __eq__(self, other):
        if isinstance(other, str):
            return str(self.absolute()) == other or str(self) == other
        elif isinstance(other, _PathType):
            return str(self.absolute()) == str(other.absolute())
        return super().__eq__(other)

__all__ = ['Path',]

PROJECT_DIR = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
'''project directory, the root directory of the project.'''

SOURCE_DIR = PROJECT_DIR / 'source'
'''source directory, for all source code.'''

ENGINE_DIR = SOURCE_DIR / 'engine'
'''engine directory, for all engine code.'''
SHADER_DIR = ENGINE_DIR / 'shaders'
'''shader directory, for all .glsl code.'''
BUILTIN_WORKFLOW_DIR = ENGINE_DIR / 'workflows' 
'''builtin workflow directory, for all builtin workflow code.'''

COMFYUI_DIR = SOURCE_DIR / 'comfyUI'
'''comfyui directory, for all comfyui code.'''
UI_DIR = SOURCE_DIR / 'ui'
'''ui directory, for ui interface source code.'''

__all__.extend(['PROJECT_DIR', 'SOURCE_DIR', 'ENGINE_DIR', 'SHADER_DIR', 'BUILTIN_WORKFLOW_DIR', 'COMFYUI_DIR', 'UI_DIR',])

RESOURCES_DIR = PROJECT_DIR / 'resources'
'''resources directory, for obj, shader, texture, etc.'''
EXAMPLE_3D_MODEL_DIR = RESOURCES_DIR / 'example-3d-models'
'''3d model directory, contains all example 3d model files for quick test.'''
EXAMPLE_MAP_OUTPUT_DIR = RESOURCES_DIR / 'example-map-outputs'
'''example map output directory, contains all example map output files for quick test.'''
EXAMPLE_WORKFLOWS_DIR = RESOURCES_DIR / 'example-workflows'

__all__.extend(['RESOURCES_DIR', 'EXAMPLE_3D_MODEL_DIR', 'EXAMPLE_MAP_OUTPUT_DIR', 'EXAMPLE_WORKFLOWS_DIR'])

TEMP_DIR = PROJECT_DIR / 'tmp'
'''temp directory, for temporary files/ test codes. This folder will not be pushed to git.'''
COMFYUI_TEMP_DIR = TEMP_DIR / 'comfyui'
'''comfyui temp directory, for temporary files/ test codes. This folder will not be pushed to git.'''

OUTPUT_DIR = PROJECT_DIR / 'output'
'''output directory, for runtime map, etc.'''
CACHE_DIR = OUTPUT_DIR / '.cache'
'''cache directory, for caching corr map'''
MAP_OUTPUT_DIR = OUTPUT_DIR / 'runtime_map'
'''runtime map output directory, for saving normal map, pos map, id map, etc., during runtime.'''
SD_COLOR_RESULT = OUTPUT_DIR / 'sd_color_result'
'''Directory for saving each frames's color output from StableDiffusion.'''
COMFYUI_OUTPUT_DIR = OUTPUT_DIR / 'comfyui'
'''comfyui output directory, for saving comfyui output files.'''
SPHERE_CACHE_DIR = OUTPUT_DIR / 'sphere_cache'
'''sphere cache directory, for saving sphere cache files.'''

INPUT_DIR = PROJECT_DIR / 'input'

__all__.extend(['TEMP_DIR', 'COMFYUI_TEMP_DIR', 'OUTPUT_DIR', 'CACHE_DIR', 'MAP_OUTPUT_DIR', 'COMFYUI_OUTPUT_DIR', 'INPUT_DIR',])


def get_new_map_output_dir(create_if_not_exists:bool=True):
    '''Return a dir under MAP_OUTPUT_DIR with current time as its name. Will create one with a unique index.'''
    count = 0
    cur_time = datetime.now().strftime('%Y-%m-%d') + f'_{count}'
    while os.path.exists(os.path.join(MAP_OUTPUT_DIR, cur_time)):
        count += 1
        cur_time = datetime.now().strftime('%Y-%m-%d') + f'_{count}'
    cur_map_output_dir = os.path.join(MAP_OUTPUT_DIR, cur_time)
    if create_if_not_exists:
        os.makedirs(cur_map_output_dir, exist_ok=True)
    return cur_map_output_dir

def get_map_output_dir(day:int, index:int, month:Optional[int]=None, year:Optional[int]=None):
    '''
    Return a subdir under MAP_OUTPUT_DIR with your specified time.
    If month or year is not specified, use current month or year.
    If no such subdir, raise FileNotFoundError.
    '''
    if month is None:
        month = datetime.datetime.now().strftime('%m')  # type: ignore
    if year is None:
        year = datetime.datetime.now().strftime('%Y')   # type: ignore
    cur_subdir = os.path.join(MAP_OUTPUT_DIR, f'{year}-{month}-{day}_{index}')
    if not os.path.exists(cur_subdir):
        raise FileNotFoundError(f'No such subdir: {cur_subdir}')
    return cur_subdir

def get_comfyUI_output_dir(time: Optional[datetime] = None, create: Optional[bool]=None)->Path:
    '''
    Get output dir for comfyUI. 
    Folder is named with the time. If not specified, use current time.
    
    Args:
        - time: Optional[datetime], default None. The time to use as the folder name.
        - create: Optional[bool], default None. The default value will depends on whether `time` is specified. If specified, default to False. If not specified, default to True.
    '''
    from common_utils.global_utils import GetGlobalValue, SetGlobalValue
    
    if not time:
        if create is None:
            create = False
        if out_dir:= GetGlobalValue('__COMFY_OUTPUT_DIR__'):
            if create:
                os.makedirs(out_dir, exist_ok=True)
            return out_dir
        else:
            time = datetime.now()
            _comfy_output_dir = Path(os.path.join(COMFYUI_OUTPUT_DIR, time.strftime('%Y-%m-%d_%H-%M-%S')))
            if create:
                os.makedirs(_comfy_output_dir, exist_ok=True)
            SetGlobalValue('__COMFY_OUTPUT_DIR__', _comfy_output_dir)
            return _comfy_output_dir
    else:
        if create is None:
            create = False
            
        _comfy_output_dir = Path(os.path.join(COMFYUI_OUTPUT_DIR, time.strftime('%Y-%m-%d_%H-%M-%S')))
        if create:
            os.makedirs(_comfy_output_dir, exist_ok=True)
        
        return _comfy_output_dir

def get_sd_color_result_dir(time: Optional[datetime] = None, create: Optional[bool]=None)->Path:
    '''
    Get output dir for sd color result. 
    Folder is named with the time. If not specified, use current time.
    
    Args:
        - time: Optional[datetime], default None. The time to use as the folder name.
        - create: Optional[bool], default None. The default value will depends on whether `time` is specified. If specified, default to False. If not specified, default to True.
    '''
    from common_utils.global_utils import GetGlobalValue, SetGlobalValue
    
    if not time:
        if create is None:
            create = False
        if out_dir:= GetGlobalValue('__SD_COLOR_RESULT_DIR__'):
            if create:
                os.makedirs(out_dir, exist_ok=True)
            return out_dir
        else:
            time = datetime.now()
            _sd_color_result_dir = Path(os.path.join(SD_COLOR_RESULT, time.strftime('%Y-%m-%d_%H-%M-%S')))
            if create:
                os.makedirs(_sd_color_result_dir, exist_ok=True)
            SetGlobalValue('__SD_COLOR_RESULT_DIR__', _sd_color_result_dir)
            return _sd_color_result_dir
    else:
        if create is None:
            create = False
            
        _sd_color_result_dir = Path(os.path.join(SD_COLOR_RESULT, time.strftime('%Y-%m-%d_%H-%M-%S')))
        if create:
            os.makedirs(_sd_color_result_dir, exist_ok=True)
        
        return _sd_color_result_dir

__all__.extend(['get_new_map_output_dir', 'get_map_output_dir', 'get_comfyUI_output_dir', 'get_sd_color_result_dir'])


def extract_index(file_path, i):
    file_name = os.path.basename(file_path)
    if file_name.split('.')[0].split('_')[-1].isdigit():  # e.g. depth_0.png
        return int(file_name.split('.')[0].split('_')[-1])
    elif file_name.split('_')[0].isdigit():   # e.g. 0_depth.png
        return int(file_name.split('_')[0])
    return i    # default to the original ordering


__all__.extend(['extract_index'])