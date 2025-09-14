from dataclasses import dataclass, field
from typing import List, Optional

# --- Helper Classes ---

class VertexFormat:
    def __init__(self, format_list: List[int]):
        self.data = format_list
    @property
    def stride(self) -> int: return sum(self.data)
    def _get_offset(self, i: int) -> int:
        if i >= len(self.data) or self.data[i] == 0: return -1
        return sum(self.data[:i])
    @property
    def position_offset(self) -> int: return self._get_offset(0)
    @property
    def normal_offset(self) -> int: return self._get_offset(1)
    def get_uv_offset(self, i: int) -> int: return self._get_offset(4 + i)

# --- Dataclasses for EDM Structures ---

@dataclass
class MatrixD: data: List[float]
@dataclass
class MatrixF: data: List[float]
@dataclass
class Vec3d: x: float; y: float; z: float

@dataclass
class Node:
    name: str
    properties: dict = field(default_factory=dict)
    transform: Optional[MatrixD] = None

@dataclass
class TextureDef:
    index: int
    filename: str
    transform: MatrixF

@dataclass
class Material:
    name: str = ""
    textures: List[TextureDef] = field(default_factory=list)
    uniforms: dict = field(default_factory=dict)
    vertex_format: Optional[VertexFormat] = None
    
@dataclass
class RootNode(Node):
    materials: List[Material] = field(default_factory=list)
    bounding_box_min: Optional[Vec3d] = None
    bounding_box_max: Optional[Vec3d] = None

@dataclass
class RenderNode(Node):
    material_id: int = 0
    parent_data: list = field(default_factory=list)
    vertices: list = field(default_factory=list)
    indices: list = field(default_factory=list)

@dataclass
class Key: frame: float; value: list
@dataclass
class ArgAnimationData: argument: int; keys: List[Key]

@dataclass
class ArgAnimationNode(Node):
    position_data: List[ArgAnimationData] = field(default_factory=list)
    rotation_data: List[ArgAnimationData] = field(default_factory=list)
    scale_data: List[ArgAnimationData] = field(default_factory=list)

@dataclass
class EdmFile:
    version: int = 0
    root_node: Optional[RootNode] = None
    nodes: List[Node] = field(default_factory=list)
    node_parents: List[int] = field(default_factory=list)
    materials: List[Material] = field(default_factory=list)
