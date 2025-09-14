import bpy
from mathutils import Matrix
from .edm.types import RenderNode, Node, ArgAnimationNode

class EdmImporter:
    def __init__(self, edm_file, context, filepath):
        self.edm_file = edm_file
        self.context = context
        self.filepath = filepath
        self.blender_objects = {} # To store newly created objects for parenting
        self.blender_materials = {} # To store newly created materials

    def run(self):
        print("Starting EDM to Blender import process...")
        self._create_materials()
        self._create_objects()
        self._build_hierarchy()
        self._apply_animations()
        print("Import process finished.")

    def _apply_animations(self):
        for i, edm_node in enumerate(self.edm_file.nodes):
            if i not in self.blender_objects:
                continue

            blender_obj = self.blender_objects[i]

            if isinstance(edm_node, ArgAnimationNode):
                if not blender_obj.animation_data:
                    blender_obj.animation_data_create()

                action = bpy.data.actions.new(name=blender_obj.name + "_Action")
                blender_obj.animation_data.action = action

                # Position
                for anim_data in edm_node.position_data:
                    for i in range(3): # X, Y, Z
                        fcurve = action.fcurves.new(data_path="location", index=i)
                        for key in anim_data.keys:
                            fcurve.keyframe_points.insert(frame=key.frame, value=key.value[i])

                # Rotation (Quaternion)
                for anim_data in edm_node.rotation_data:
                    blender_obj.rotation_mode = 'QUATERNION'
                    for i in range(4): # W, X, Y, Z
                        fcurve = action.fcurves.new(data_path="rotation_quaternion", index=i)
                        for key in anim_data.keys:
                            # EDM is XYZW, Blender is WXYZ
                            quat_val = key.value
                            blender_quat = [quat_val[3], quat_val[0], quat_val[1], quat_val[2]]
                            fcurve.keyframe_points.insert(frame=key.frame, value=blender_quat[i])

                # Scale
                for anim_data in edm_node.scale_data:
                    for i in range(3): # X, Y, Z
                        fcurve = action.fcurves.new(data_path="scale", index=i)
                        for key in anim_data.keys:
                            # EDM scale has 4 components, we use the first 3
                            fcurve.keyframe_points.insert(frame=key.frame, value=key.value[i])

    def _create_materials(self):
        import os
        base_dir = os.path.dirname(self.filepath)

        for i, edm_mat in enumerate(self.edm_file.materials):
            mat = bpy.data.materials.new(name=edm_mat.name)
            mat.use_nodes = True
            self.blender_materials[i] = mat

            nodes = mat.node_tree.nodes
            bsdf = nodes.get('Principled BSDF')
            if not bsdf:
                continue

            # Texture mapping
            for tex_def in edm_mat.textures:
                # As per user: Textures are in a 'textures' subfolder inside a zip.
                # For now, let's assume they are extracted and accessible.
                # A common layout is ../textures/ or ./textures/
                tex_path_rel = tex_def.filename
                # A robust implementation would search multiple paths
                tex_path_abs = os.path.join(base_dir, '..', 'textures', tex_path_rel)
                if not os.path.exists(tex_path_abs):
                     tex_path_abs = os.path.join(base_dir, tex_path_rel) # Try local path too

                if os.path.exists(tex_path_abs):
                    tex_node = nodes.new('ShaderNodeTexImage')
                    tex_node.image = bpy.data.images.load(tex_path_abs, check_existing=True)

                    # Connect based on texture type index from spec
                    if tex_def.index == 0: # Diffuse
                        mat.node_tree.links.new(bsdf.inputs['Base Color'], tex_node.outputs['Color'])
                    elif tex_def.index == 1: # Normals
                        normal_map_node = nodes.new('ShaderNodeNormalMap')
                        tex_node.image.colorspace_settings.name = 'Non-Color'
                        mat.node_tree.links.new(normal_map_node.inputs['Color'], tex_node.outputs['Color'])
                        mat.node_tree.links.new(bsdf.inputs['Normal'], normal_map_node.outputs['Normal'])
                    elif tex_def.index == 2: # Specular
                        # Specular maps can control roughness, specularity, or metallic.
                        # A common workflow is to use it for roughness.
                        # We'll connect it to Roughness for now.
                        spec_node = nodes.new('ShaderNodeSeparateRGB') # Assuming it's grayscale
                        mat.node_tree.links.new(spec_node.inputs['Image'], tex_node.outputs['Color'])
                        mat.node_tree.links.new(bsdf.inputs['Roughness'], spec_node.outputs['R'])

            # Uniform mapping (simplified)
            if 'diffuseValue' in edm_mat.uniforms:
                # This is often a color, needs parsing
                pass
            if 'specFactor' in edm_mat.uniforms:
                # bsdf.inputs['Specular'].default_value = edm_mat.uniforms['specFactor']
                pass

    def _create_objects(self):
        # First pass: create all objects
        for i, node in enumerate(self.edm_file.nodes):
            obj = None
            if isinstance(node, RenderNode):
                mesh = self._create_mesh_for_node(node)
                obj = bpy.data.objects.new(node.name, mesh)
            else: # For TransformNode, Node, etc.
                obj = bpy.data.objects.new(node.name, None)

            if obj:
                # Apply transform if it exists
                if node.transform:
                    # EDM matrices are column-major, 4x4. Blender's are also 4x4.
                    # We need to create a Blender Matrix from the raw float data.
                    # The data is a list of 16 floats/doubles.
                    m = node.transform.data
                    mat = Matrix((m[0:4], m[4:8], m[8:12], m[12:16]))
                    mat.transpose() # Transpose to convert from column-major list to row-major constructor
                    obj.matrix_basis = mat

                self.blender_objects[i] = obj
                self.context.collection.objects.link(obj)

    def _create_mesh_for_node(self, node: RenderNode):
        mesh = bpy.data.meshes.new(name=node.name + "_mesh")

        # 1. Get the material and vertex format for this node
        if node.material_id >= len(self.edm_file.materials):
            print(f"Warning: Material ID {node.material_id} out of bounds for node {node.name}")
            return mesh # Return empty mesh

        material = self.edm_file.materials[node.material_id]
        vert_format = material.vertex_format
        vert_stride = sum(vert_format)

        if not vert_format or not node.vertices:
            return mesh # Not enough data to build a mesh

        # 2. Use VertexFormat to get offsets
        vert_format = material.vertex_format
        if not vert_format:
            print(f"Warning: No vertex format for material '{material.name}'")
            return mesh

        pos_offset = vert_format.position_offset
        norm_offset = vert_format.normal_offset

        if pos_offset == -1:
            print(f"Warning: No position data in vertex format for node {node.name}")
            return mesh

        # 3. Extract data from the flat vertex buffer
        positions = []
        normals = []
        uv_layers = {} # uv_layers[0] = [uv1, uv2, ...]

        num_verts = len(node.vertices) // vert_format.stride
        for i in range(num_verts):
            vert_start = i * vert_format.stride

            positions.append(node.vertices[vert_start + pos_offset : vert_start + pos_offset + 3])

            if norm_offset != -1:
                normals.append(node.vertices[vert_start + norm_offset : vert_start + norm_offset + 3])

            # UVs
            for uv_channel in range(8): # Check up to 8 UV channels
                uv_offset = vert_format.get_uv_offset(uv_channel)
                if uv_offset != -1:
                    if uv_channel not in uv_layers:
                        uv_layers[uv_channel] = []
                    u, v = node.vertices[vert_start + uv_offset : vert_start + uv_offset + 2]
                    uv_layers[uv_channel].append((u, 1.0 - v)) # Flip V coordinate

        # 4. Create faces (triangles)
        faces = []
        for i in range(0, len(node.indices), 3):
            faces.append(node.indices[i:i+3])

        # 5. Populate the mesh
        mesh.from_pydata(positions, [], faces)

        # Set normals
        if normals:
            mesh.normals_split_custom_set_from_vertices(normals)
            mesh.use_auto_smooth = True

        # Create UV layers and populate them
        for uv_key, uv_data in uv_layers.items():
            if uv_data:
                uv_layer = mesh.uv_layers.new(name=uv_key)
                # The UV data needs to be reshaped for per-loop assignment
                loop_uvs = [0.0] * (len(mesh.loops) * 2)
                for loop in mesh.loops:
                    loop_uvs[loop.index * 2 : loop.index * 2 + 2] = uv_data[loop.vertex_index]
                uv_layer.data.foreach_set("uv", loop_uvs)

        mesh.update()
        mesh.validate()

        # Assign material
        if node.material_id in self.blender_materials:
            mesh.materials.append(self.blender_materials[node.material_id])

        return mesh

    def _build_hierarchy(self):
        for i, parent_index in enumerate(self.edm_file.node_parents):
            if parent_index != 0xFFFFFFFF and i in self.blender_objects and parent_index in self.blender_objects:
                child_obj = self.blender_objects[i]
                parent_obj = self.blender_objects[parent_index]
                child_obj.parent = parent_obj
