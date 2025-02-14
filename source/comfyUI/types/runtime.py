import torch
from deprecated import deprecated
from typing import (Union, TypeAlias, Literal, Optional, List, Any, Type, Dict, Tuple, TYPE_CHECKING, 
                    Sequence, TypeVar, Generic, Set, NamedTuple, Union, Callable, Any, NewType)
from attr import attrs, attrib
from dataclasses import dataclass
from collections import OrderedDict
from common_utils.debug_utils import ComfyUILogger
from common_utils.type_utils import get_cls_name, NameCheckMetaCls
from common_utils.decorators import singleton, Overload

from ._utils import get_node_cls_by_name

if TYPE_CHECKING:
    from .hidden import PROMPT
    from .basic import IMAGE
    from .node_base import ComfyUINode
    from comfy.conds import CONDRegular


_CT = TypeVar('_CT')

class ComfyCacheDict(Dict[Tuple[str, str], _CT], Generic[_CT]):
    '''
    ComfyCacheDict is a special dictionary that stores the data for each node.
    
    The data structure is actually {(node_id, node_type): value, ...}, 
    but you could still access it by only providing the node_id(its for compatibility with old code).
    '''
    
    _ToBeDeleted: Dict[Tuple[str, str], _CT] = OrderedDict()
    '''
    Deleted values will not be remove immediately. They are passing to this list, and wait for future reuse or delete.
    Too-old items will be removed by LRU strategy. 
    '''
    USELESS_CACHE_MAX_COUNT = 32
    '''how many useless items can be stored in the pool.'''
    
    def __getitem__(self, key: Union[str, Tuple[str, str]]) -> Any:
        if isinstance(key, str):
            return self.find_by_node_id(key, raise_err=True)
        if key in self._ToBeDeleted:
            self[key] = self._ToBeDeleted.pop(key)
        return super().__getitem__(key)
    
    def __setitem__(self, key: Tuple[str, str], val):
        if isinstance(key, str):
            node = NodePool.Instance().find_by_node_id(key)
            if not node:
                raise KeyError(f'Node id `{key}` not found.')
            key = (key, node.NAME)
        if key in self._ToBeDeleted:
            del self._ToBeDeleted[key]  # no need old value anymore
        super().__setitem__(key, val)
    
    def find_by_node_id(self, id: str, raise_err: bool = False):
        for (node_id, node_type), val in self.items():
            if node_id == id:
                return val
        for (node_id, node_type), val in self._ToBeDeleted.items():
            if node_id == id:
                self[(node_id, node_type)] = self._ToBeDeleted.pop((node_id, node_type))
                return self[(node_id, node_type)]
        if raise_err:
            raise KeyError(f'Node id not found: {id}.')
        return None
        
    def clear_cache(self):
        '''clear the `nodes to be deleted` cache.'''
        self._ToBeDeleted.clear()
        
    def clear(self, clear_cache=True):
        '''
        clear all nodes in the pool.
        If clear_cache=True, `nodes to be deleted` will also be cleared.
        '''
        if clear_cache:
            self.clear_cache()
        super().clear()    
    
    def _check_if_node_should_be_deleted(self):
        if len(self._ToBeDeleted) > self.USELESS_CACHE_MAX_COUNT:
            for key in tuple(self._ToBeDeleted.keys())[:self.USELESS_CACHE_MAX_COUNT//2]:
                del self._ToBeDeleted[key]
    
    @Overload
    def delete(self, node: "ComfyUINode"):  # type: ignore
        node_type_name = node.NAME if hasattr(node, 'NAME') else node.__class__.__qualname__
        return self.delete(node.ID, node_type_name)
    
    @Overload
    def delete(self, node_id: str, node_type: str):
        '''if node is not in pool, this will do nothing.'''
        if (node_id, node_type) in self:
            self._ToBeDeleted[(node_id, node_type)] = self.pop((node_id, node_type))
            self._check_if_node_should_be_deleted()
    
@attrs
class InferenceOutput:
    '''The output of an inference process(when running through engine).'''
    
    frame_color: "IMAGE" = attrib(default=None)
    '''The final color output of this frame.'''

@singleton(cross_module_singleton=True)
class NodePool(ComfyCacheDict["ComfyUINode"]):
    '''
    {(node_id, node_type): node_instance, ...}
    The global pool of all created nodes.
    
    This node pool is not exactly the same structure as the original ComfyUI's node pool,
    because the original design is not that good, it set the node type name as a part of the key,
    but it is not necessary to do that (nodes always have unique id).
    '''
    
    def _check_if_node_should_be_deleted(self):
        if len(self._ToBeDeleted) > self.USELESS_CACHE_MAX_COUNT:
            for key in tuple(self._ToBeDeleted.keys())[:self.USELESS_CACHE_MAX_COUNT//2]:
                node = self._ToBeDeleted.pop(key)
                if hasattr(node, 'ON_DESTROY'):
                    try:
                        node.ON_DESTROY()
                    except Exception as e:
                        ComfyUILogger.error(f'Error when calling ON_DESTROY for node with id={node.ID}({node.__class__.__qualname__}): {e}, ignored.')
                del node
    
    @classmethod
    def Instance(cls)->'NodePool':
        '''Get the global instance of the node pool.'''
        return cls.__instance__  # type: ignore
    
    @Overload
    def delete(self, node: "ComfyUINode"):  # type: ignore
        node_type_name = node.NAME if hasattr(node, 'NAME') else node.__class__.__qualname__
        return self.delete(node.ID, node_type_name)
    
    @Overload
    def delete(self, node_id: str, node_type: str):
        '''if node is not in pool, this will do nothing.'''
        if (node_id, node_type) in self:
            self._ToBeDeleted[(node_id, node_type)] = self.pop((node_id, node_type))
            self._check_if_node_should_be_deleted()
    
    def get_or_create(self, node_id: str, node_type: str):
        if (node_id, node_type) in self:
            return self[(node_id, node_type)]
        
        elif (node_id, node_type) in self._ToBeDeleted:
            node = self._ToBeDeleted.pop((node_id, node_type))
            self[(node_id, node_type)] = node
            return node
        
        node_cls = get_node_cls_by_name(node_type)
        if not node_cls:
            raise ValueError(f'Invalid node type name: {node_type}.')
        node = node_cls()
        node.ID = node_id
        self[(node_id, node_type)] = node
        return node
       
    def clear_cache(self):
        '''clear the `nodes to be deleted` cache.'''
        for _, node in self._ToBeDeleted.items():
            if hasattr(node, 'ON_DESTROY'):
                try:
                    node.ON_DESTROY()
                except Exception as e:
                    ComfyUILogger.error(f'Error when calling ON_DESTROY for node with id={node.ID}({node.NAME}): {e}, ignored.')
        self._ToBeDeleted.clear()
        
    def clear(self, clear_cache=True):
        '''
        clear all nodes in the pool.
        If clear_cache=True, `nodes to be deleted` will also be cleared.
        '''
        if clear_cache:
            self.clear_cache()
        
        for _, node in self.items():
            if hasattr(node, 'ON_DESTROY'):
                try:
                    node.ON_DESTROY()
                except Exception as e:
                    ComfyUILogger.error(f'Error when calling ON_DESTROY for node with id={node.ID}({node.NAME}): {e}, ignored.')
        super().clear()

class NodeBindingParam(Tuple[str, int], metaclass=NameCheckMetaCls()):
    '''
    (node_id, output_slot_index)
    The tuple contains the information that the input value of a node is from another node's output.
    '''
    
    def __repr__(self):
        return f'NodeBindingParam({self[0]}, {self[1]})'
    
    def __eq__(self, __value: object) -> bool:
        if isinstance(__value, Sequence) and len(__value) ==2:
            return self[0] == __value[0] and self[1] == __value[1]
        return super().__eq__(__value)
    
    def __hash__(self) -> int:
        return super().__hash__()
    
    @property
    def from_node_id(self)->str:
        '''The node id of the source node. Wrapper for the first element of the tuple.'''
        return self[0]
    
    @property
    def from_node(self):
        return NodePool.Instance().find_by_node_id(self.from_node_id)
    
    @property
    def output_slot_index(self)->int:
        '''The output slot index of the source node. Wrapper for the second element of the tuple.'''
        return self[1]

class NodeInputs(Dict[str, Union[NodeBindingParam, Any]], metaclass=NameCheckMetaCls()):
    '''
    {param_name: input_value, ...}
    
    There are 2 types of dict value:
        - [node_id(str), output_slot_index(int)]: the input is from another node
        - Any: the input is a value
    '''
    
    def _should_convert_to_bind_type(self, value: list)->bool:
        if isinstance(value, NodeBindingParam):
            return False    # already binding
        if len(value)!=2 or not isinstance(value[0], str) or not isinstance(value[1], int): 
            return False    # not binding
        return True         # seems like a binding, e.g. ['1', 0] means from node_id=1 and output_slot_index=0
    
    def _format_values(self):
        all_param_dict = {}
        all_param_dict.update(self.node_type.INPUT_TYPES().get('required', {}))
        all_param_dict.update(self.node_type.INPUT_TYPES().get('optional', {}))
        all_param_dict.update(self.node_type.INPUT_TYPES().get('hidden', {}))
        
        advanced_node_input_type_def = {}
        if hasattr(self.node_type, '__ADVANCED_NODE_CLASS__') and self.node_type.__ADVANCED_NODE_CLASS__:
            advanced_node_input_type_def = self.node_type.__ADVANCED_NODE_CLASS__._InputFields
            
        for key, value in tuple(self.items()):
            if key not in all_param_dict:
                continue    # ignore unknown input
            param_type = all_param_dict[key][0] # (type, param info)
            converted_to_binding = False
            
            if isinstance(value, NodeBindingParam):
                if key not in self._links:
                    self._links[key] = []
                self._links[key].append(value)
        
            elif isinstance(value, list):
                if self._should_convert_to_bind_type(value):
                    self[key] = NodeBindingParam(value)
                    if key not in self._links:
                        self._links[key] = []
                    self._links[key].append(self[key])
                    converted_to_binding = True
            
            if not converted_to_binding:
                if isinstance(param_type, type):
                    if hasattr(param_type, "__ComfyLoad__"):
                        self[key] = param_type.__ComfyLoad__(value)
                elif key in advanced_node_input_type_def:
                    param_type = advanced_node_input_type_def[key].origin_type    
                    if isinstance(param_type, type) and hasattr(param_type, "__ComfyLoad__"):
                        self[key] = param_type.__ComfyLoad__(value)
    
    node_id: str
    '''Which node this input belongs to.'''
    node_type_name: str
    '''The origin node type of this input's node.'''
    node_type: Type["ComfyUINode"]
    '''The origin node type of this input's node.'''
    _links: Dict[str, List[NodeBindingParam]]
    '''input links from other nodes to this node. {input_name: (from_node_id, output_slot_index)}'''

    @property
    def links(self):
        return self._links

    def __init__(self, node_id:str, node_type_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.node_id = node_id
        self.node_type_name = node_type_name
        self.node_type = get_node_cls_by_name(node_type_name)  # type: ignore
        if not self.node_type:
            raise ValueError(f'Invalid node type name: {node_type_name}.')    
        self._links = {}
        self._format_values() # make sure all values are Any/FromNodeInput

    def __setitem__(self, __key: str, __value: Union[NodeBindingParam, Any]) -> None:
        if (
            isinstance(__value, list) and
            len(__value)==2 and 
            not isinstance(__value, NodeBindingParam) and
            isinstance(__value[0], str) and
            isinstance(__value[1], int)
        ):
            __value = NodeBindingParam(*__value)
            self._links[__key] = [__value]
            
        super().__setitem__(__key, __value)

StatusMsgEvent: TypeAlias = Literal['status', 'progress', 'executing', 'executed', 'execution_start', 'execution_error', 'execution_cached', 'execution_interrupted']
'''The status message event type for PromptExecutor. See source/comfyUI/web/scripts/api.js'''

StatusMsgs: TypeAlias = List[Tuple[StatusMsgEvent, Dict[str, Any]]]
'''
The status message type for PromptExecutor.
[(event, {msg_key: msg_value, ...}), ...]
'''

QueueTask: TypeAlias = Tuple[Union[int, float], str, "PROMPT", dict, list]
'''
The type hint for the queue task in execution.PromptQueue's inner items
Items:
    - number (int? float? seems int but i also saw number=float(...), too strange, and idk wtf is this for)
    - prompt_id (str, random id by uuid4)
    - prompt    (for PromptExecutor.execute method)
    - extra_data
    - outputs_to_execute (node ids to be e)
'''

class ConvertedCondition(Dict[str, Any]):
    '''
    Type hints for single converted conditioning in `comfyUI/comfy/sample.py/convert_cond` function.
    It was known to have the following structure:
    { 
        "some_output_a": Any, 
        "cross_attn": cond_tensor_a,
        "model_conds": {
            "c_crossattn": comfy.conds.CONDCrossAttn(cond_tensor_a),
            ...
        }
    }
    Refer to CONDITIONING datatype or convert_cond() docstrings for more information.
    '''
    @property
    def cross_attn(self):
        '''The cross attention tensor'''
        return self['cross_attn']
    
    @property
    def pooled_output(self):
        '''
        The pooled output tensor
        Not sure what is the actual meaning of this.
        '''
        return self['pooled_output']
    
    @property
    def model_conds(self)->Dict[str, "CONDRegular"]:
        '''The model conditions'''
        return self['model_conds']
    

class RecursiveExecuteResult(NamedTuple):
    '''result return type for _recursive_execute in execution.py'''
    
    success: bool
    '''whether the execution is successful or not'''
    error_details: Optional[dict]
    '''the error details if the execution is failed'''
    exception: Optional[Exception]
    '''the exception if the execution is failed'''

@dataclass
class ValidateInputsResult:
    '''dataclass for the result of `validate_inputs` function.'''
    
    success: bool
    '''whether the validation is successful or not'''
    errors: List[dict]
    '''list of error messages'''
    node_id: str
    '''the node id that is being validated'''

    def __getitem__(self, item: int):
        if item not in (0, 1, 2):
            raise IndexError(f"Index out of range: {item}")
        if item == 0:
            return self.success
        if item == 1:
            return self.errors
        if item == 2:
            return self.node_id

@dataclass
class ValidatePromptResult:
    '''dataclass for the result of `validate_prompt` function.'''
    
    result: bool
    '''whether the validation is successful or not'''
    errors: Optional[dict]
    '''the error messages if the validation failed'''
    nodes_with_good_outputs: List[str]
    '''list of output node ids that passed the validation.'''
    node_errors: Dict[str, dict]
    '''dict of node_id: error messages'''

    _prompt: dict
    '''The real input prompt, a dictionary (converted from json)'''
    _prompt_id: str
    '''unique id of the prompt, a random string by uuid4. This can be None to make it compatible with old comfyUI codes.'''
    _formatted_prompt: Optional["PROMPT"] = None
    '''The properly formatted prompt, in `PROMPT` type'''
    
    @property
    def formatted_prompt(self)->"PROMPT":
        from .hidden import PROMPT
        if not self._formatted_prompt:
            if not isinstance(self._prompt, PROMPT):
                self._formatted_prompt = PROMPT(self._prompt, id=self._prompt_id)
            else:
                self._formatted_prompt = self._prompt
        return self._formatted_prompt
    
    def __getitem__(self, item: int):
        if item not in (0, 1, 2, 3, 4):
            raise IndexError(f"Index out of range: {item}. It should be in [0, 1, 2, 3, 4]")
        if item == 0:
            return self.result
        if item == 1:
            return self.errors
        if item == 2:
            return self.nodes_with_good_outputs
        if item == 3:
            return self.node_errors
        if item == 4:
            return self.formatted_prompt

_T = TypeVar('_T')
_MT = TypeVar('_MT') 
class NODE_MAPPING(Dict[Tuple[str, str], _MT], Generic[_MT]):
    '''
    Node mappings dict, e.g. `NODE_CLASS_MAPPINGS`, `NODE_DISPLAY_NAME_MAPPINGS`,... in `nodes.py`.
    This class allows you to find node in this mapping with just `node_type_name` or (node_type_name, namespace).
    '''
    
    class NodeMappingKey(str):
        '''
        This class acts as the key when u iterating `NODE_MAPPING` dict.
        It is for the compatibility with old code.
        '''
        
        cls_name: str
        namespace: str
        origin_tuple: Tuple[str, str]
        
        def __new__(cls, cls_name_and_namespace: Tuple[str, str]):
            ins = super().__new__(cls, cls_name_and_namespace[0])
            ins.cls_name = cls_name_and_namespace[0]
            ins.namespace = cls_name_and_namespace[1]
            ins.origin_tuple = cls_name_and_namespace
            return ins
        
        def __len__(self):
            return 2
        
        def __iter__(self):
            return iter(self.origin_tuple)

        def __getitem__(self, key) -> str:
            return self.origin_tuple[key]
        
        def __hash__(self):
            return hash(self.cls_name)
        
        def __eq__(self, other: Union[Tuple[str, str], str]):
            if isinstance(other, tuple):
                if len(other)!=2:
                    return False
                return self.cls_name == other[0] and self.namespace == other[1]
            elif isinstance(other, str):
                return self.cls_name == other
            return False

        def __str__(self):
            return self.cls_name
        
        def __repr__(self) -> str:
            return self.cls_name
    
    def __class_getitem__(cls, t: _T) -> 'Type[NODE_MAPPING[_T]]':
        # this is just acting as a type hint
        return cls  # type: ignore
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key in tuple(super().keys()):
            if isinstance(key, str):
                super().__setitem__((key, ""), super().pop(key))    # `""` means default namespace
    
    def __getitem__(self, key: Union[str, type, Tuple[Union[str, type], Union[str, None]]]) -> _MT:
        if isinstance(key, (list, tuple)):
            if len(key) not in (1,2):
                raise ValueError(f'Invalid key: {key}, it should be a tuple with 2 elements(node_type_name, namespace).')
            node_type_name = key[0]
            node_namespace = key[1] if len(key)==2 else None
        else:
            node_type_name = key
            node_namespace = None
        if isinstance(node_type_name, type):
            node_type_name = get_cls_name(node_type_name)
        node_namespace = node_namespace.strip() if node_namespace else None
        node_namespace = "" if node_namespace is None else node_namespace   # `""` means default namespace
        try:
            return super().__getitem__((node_type_name, node_namespace))
        except KeyError as e:
            if node_namespace:   # namespace is specified but not found
                raise e
            for key in tuple(super().keys()):
                if key[0] == node_type_name:
                    return super().__getitem__(key)
            raise KeyError(f'Node not found: {node_type_name} in namespace {node_namespace}.')
    
    def __setitem__(self, key: Union[str, type, Tuple[Union[str, type], Union[str, None]]], value: _MT) -> None:
        if isinstance(key, (list, tuple)):
            if len(key) not in (1,2):
                raise ValueError(f'Invalid key: {key}, it should be a tuple with 2 elements(node_type_name, namespace).')
            node_type_name = key[0]
            node_namespace = key[1] if len(key)==2 else None
        else:
            node_type_name = key
            node_namespace = None
        if isinstance(node_type_name, type):
            node_type_name = get_cls_name(node_type_name)
        node_namespace = node_namespace.strip() if node_namespace else None
        node_namespace = "" if node_namespace is None else node_namespace   # `""` means default namespace
        super().__setitem__((node_type_name, node_namespace), value)

    def keys(self):
        return self.__iter__()

    def __iter__(self):
        for key in super().keys():
            yield NODE_MAPPING.NodeMappingKey(key)

@attrs
class SamplingCallbackContext:
    '''context during sampling.'''
    
    noise: torch.Tensor = attrib()
    '''The noise tensor for sampling.'''
    step_index: int = attrib()
    '''The current step index'''
    denoised: torch.Tensor = attrib()
    '''the denoised latent'''
    total_steps: int = attrib()
    '''The total steps of sampling.'''
    timesteps: List[int] = attrib()
    '''all time steps of the sampling.'''
    sigmas: List[float] = attrib()
    '''all sigma values. It is actually a list-like float tensor.'''
        
    # region deprecated
    @property
    @deprecated(reason='use `noise` instead.')
    def x(self)->torch.Tensor:
        '''The noise tensor for sampling.'''
        return self.noise
    
    @property
    @deprecated(reason='use `step_index` instead')
    def i(self)->int:
        '''step index of the sampling.'''
        return self.step_index
    # endregion
    
    @property
    def sampling_progress(self)->float:
        '''The progress ratio of the sampling, i.e. step_index/total_steps.'''
        return self.step_index / self.total_steps
    
    @property
    def sigma(self)->float:
        '''The sigma value of current step.'''
        return self.sigmas[self.step_index]
    
    @property
    def timestep(self):
        '''return current timestep'''
        return self.timesteps[self.step_index]
    
    @property
    def timestep_ratio(self):
        '''return the ratio of current progress regarding to the initial timestep=1000, i.e. self.timestep/1000.'''
        return self.timestep / 1000
    

SamplerCallback: TypeAlias = Union[
    Callable[[], Any],  # no arguments
    Callable[[SamplingCallbackContext], Any],    # pass context
    Callable[[int, torch.Tensor, torch.Tensor, int], Any]   # pass (i, denoised, x, total_steps)
]
'''callback when a inference step is finished''' 

VAEDecodeCallback: TypeAlias = Callable[['IMAGE'], Any]
globals()['VAEDecodeCallback'] = NewType("VAEDecodeCallback", Callable[['IMAGE'], Any])     # type: ignore
# tricks for making `VAEDecodeCallback` have a `__name__` attribute



__all__ = ['InferenceOutput', 'SamplingCallbackContext', 'SamplerCallback', 'VAEDecodeCallback',
                
            'ComfyCacheDict', 'NodePool', 'NodeBindingParam', 'NodeInputs', 
            
            'StatusMsgEvent', 'StatusMsgs', 'QueueTask', 'ConvertedCondition', 
            
            'RecursiveExecuteResult', 'ValidateInputsResult', 'ValidatePromptResult',
            
            'NODE_MAPPING']
