"""Save the heart's solid parts (no outline markers) into a small standalone .blend."""
import bpy, sys
keep = [o for o in bpy.data.collections["Heart"].all_objects if o.type == "MESH" and not o.name.endswith(".j") and max(o.dimensions) > 0.01]
keep.append(bpy.data.objects["Pulmonary trunk"])
bpy.context.view_layer.update()
for o in keep:  # bake in each part's true position: its parents stay behind in the atlas
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
    o.modifiers.clear()
    o.constraints.clear()
data = set(keep) | {o.data for o in keep}
bpy.data.libraries.write("/tmp/za/assets/heart.blend", data, fake_user=True, compress=True)
sys.stderr.write("SAVED %d parts\n" % len(keep))
