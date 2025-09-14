import bpy
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator
from bpy.props import StringProperty

from .edm.parser import EdmParser
from .importer import EdmImporter

class ImportEDM(Operator, ImportHelper):
    """Import an EDM file"""
    bl_idname = "import_scene.edm"
    bl_label = "Import EDM"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".edm"
    filter_glob: StringProperty(
        default="*.edm",
        options={'HIDDEN'},
    )

    def execute(self, context):
        print(f"Importing EDM file from: {self.filepath}")

        try:
            parser = EdmParser(self.filepath)
            edm_file = parser.parse()

            if edm_file:
                importer = EdmImporter(edm_file, context, self.filepath)
                importer.run()
                self.report({'INFO'}, "EDM file imported successfully.")
            else:
                self.report({'ERROR'}, "Failed to parse EDM file.")
                return {'CANCELLED'}

        except Exception as e:
            self.report({'ERROR'}, f"An error occurred: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        return {'FINISHED'}

def menu_func_import(self, context):
    self.layout.operator(ImportEDM.bl_idname, text="DCS EDM (.edm)")

def register_menu_functions():
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister_menu_functions():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
