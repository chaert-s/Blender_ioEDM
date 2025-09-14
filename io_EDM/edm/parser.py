import struct
from .types import *

class EdmParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.stream = None
        self.version = 0
        self.string_lookup = []
        self._setup_parsers()

    def _setup_parsers(self):
        self._type_parsers = {
            "model::RootNode": self._read_root_node,
            "model::Node": self._read_node,
            "model::TransformNode": self._read_transform_node,
            "model::RenderNode": self._read_render_node,
            "model::ArgAnimationNode": self._read_arg_animation_node,
            "model::ArgRotationNode": self._read_arg_animation_node,
            "model::ArgPositionNode": self._read_arg_animation_node,
            "model::Property<unsigned int>": lambda: {"name": self._read_string(), "value": self._read_uint()},
            "model::Property<float>": lambda: {"name": self._read_string(), "value": self._read_float()},
        }
        self._material_key_parsers = {
            "BLENDING": ("blending", self._read_uchar), "CULLING": (None, self._read_uchar),
            "DEPTH_BIAS": (None, self._read_uint), "TEXTURES": ("textures", lambda: self._read_list(self._read_texture_def)),
            "MATERIAL_NAME": ("material_name", self._read_string), "NAME": ("name", self._read_string),
            "SHADOWS": (None, self._read_uchar), "VERTEX_FORMAT": ("vertex_format", lambda: VertexFormat(self._read_list(self._read_uchar))),
            "UNIFORMS": ("uniforms", self._read_properties_set), "ANIMATED_UNIFORMS": (None, self._read_properties_set),
            "TEXTURE_COORDINATE_CHANNELS": (None, lambda: self._read_list(self._read_uint)),
        }

    def parse(self):
        with open(self.file_path, 'rb') as f:
            self.stream = f
            if self.stream.read(3) != b'EDM': raise ValueError("Not an EDM file")
            self.version = self._read_ushort()
            if self.version == 10:
                size = self._read_uint()
                self.string_lookup = [s.decode('windows-1251', 'replace') for s in self.stream.read(size).split(b'\x00') if s]

            self._read_map() # Skip IndexA
            self._read_map() # Skip IndexB

            edm_file = EdmFile(version=self.version)
            edm_file.root_node = self._read_named_type()
            edm_file.nodes = self._read_list(self._read_named_type)
            edm_file.node_parents = self._read_list(self._read_uint)
            edm_file.materials = edm_file.root_node.materials
            return edm_file

    def _read_string(self, is_uint_string=False):
        if self.version == 10 and not is_uint_string: return self.string_lookup[self._read_uint()]
        return self.stream.read(self._read_uint()).decode('windows-1251', errors='replace')

    def _read_list(self, reader): return [reader() for _ in range(self._read_uint())]
    def _read_map(self): return {self._read_string(): self._read_uint() for _ in range(self._read_uint())}

    def _read_named_type(self):
        type_name = self._read_string()
        parser = self._type_parsers.get(type_name)
        if parser: return parser()
        print(f"Warning: Unknown named_type '{type_name}', skipping is not robustly implemented.")
        return None

    def _read_properties_set(self):
        props = self._read_list(self._read_named_type)
        return {p['name']: p['value'] for p in props if p}

    def _read_material(self):
        mat = Material()
        for _ in range(self._read_uint()):
            key = self._read_string()
            parser_info = self._material_key_parsers.get(key)
            if parser_info:
                attr_name, parser_func = parser_info
                value = parser_func()
                if attr_name: setattr(mat, attr_name, value)
            else:
                print(f"Warning: Unknown material key '{key}', skipping by assuming it's a properties set.")
                self._read_properties_set() # Best guess for skipping
        return mat

    def _read_node_base(self):
        name = self._read_string(is_uint_string=True)
        self._read_uint() # version
        props = self._read_properties_set()
        return name, props

    def _read_root_node(self):
        name, props = self._read_node_base()
        node = RootNode(name=name, properties=props)
        self.stream.read(1) # unknownA
        node.bounding_box_min = Vec3d(self._read_double(), self._read_double(), self._read_double())
        node.bounding_box_max = Vec3d(self._read_double(), self._read_double(), self._read_double())
        self.stream.read(4 * 8)
        node.materials = self._read_list(self._read_material)
        self.stream.read(2 * 4)
        return node

    def _read_texture_def(self):
        index, _, filename, _, matrix_data = self._read_int(), self.stream.read(4), self._read_string(), self.stream.read(16), [self._read_float() for _ in range(16)]
        return TextureDef(index, filename, MatrixF(matrix_data))

    def _read_node(self):
        name, props = self._read_node_base()
        return Node(name=name, properties=props)

    def _read_transform_node(self):
        node = self._read_node()
        node.transform = MatrixD([self._read_double() for _ in range(16)])
        return node

    def _read_render_node(self):
        node = RenderNode(name=self._read_string(is_uint_string=True))
        self._read_uint() # version
        node.properties = self._read_properties_set()
        self.stream.read(4)
        node.material_id = self._read_uint()

        parent_count = self._read_uint()
        for _ in range(parent_count):
            self.stream.read(8 if parent_count == 1 else 12)

        vert_count, vert_stride = self._read_uint(), self._read_uint()
        node.vertices = [self._read_float() for _ in range(vert_count * vert_stride)]

        index_type, index_entries, _ = self._read_uchar(), self._read_uint(), self.stream.read(4)
        fmt = {0: '<B', 1: '<H', 2: '<I'}.get(index_type)
        node.indices = [struct.unpack(fmt, self.stream.read(struct.calcsize(fmt)))[0] for _ in range(index_entries)]
        return node

    def _read_arg_animation_node(self):
        node = ArgAnimationNode(name=self._read_string(is_uint_string=True))
        # This is a simplified version, skipping lots of data
        self.stream.read(8 + 8*16 + 8*3 + 4*4 + 4*4 + 8*3) # version, props, transforms
        def read_anim_data(key_type_char):
            arg = self._read_uint()
            reader = {'p':lambda:Key(self._read_double(),[self._read_double() for _ in range(3)]),
                      'r':lambda:Key(self._read_double(),[self._read_float() for _ in range(4)]),
                      's':lambda:Key(self._read_double(),[self._read_float() for _ in range(4)])}[key_type_char]
            keys = self._read_list(reader)
            if key_type_char == 's': self.stream.read(self._read_uint() * (8 + 3*4))
            return ArgAnimationData(arg, keys)
        node.position_data = self._read_list(lambda: read_anim_data('p'))
        node.rotation_data = self._read_list(lambda: read_anim_data('r'))
        node.scale_data = self._read_list(lambda: read_anim_data('s'))
        return node

    def _read_uchar(self): return struct.unpack('<B', self.stream.read(1))[0]
    def _read_ushort(self): return struct.unpack('<H', self.stream.read(2))[0]
    def _read_int(self): return struct.unpack('<i', self.stream.read(4))[0]
    def _read_uint(self): return struct.unpack('<I', self.stream.read(4))[0]
    def _read_float(self): return struct.unpack('<f', self.stream.read(4))[0]
    def _read_double(self): return struct.unpack('<d', self.stream.read(8))[0]
