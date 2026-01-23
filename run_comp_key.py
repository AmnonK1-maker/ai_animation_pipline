"""Blender compositor keying runner (Blender 5.x friendly)

Usage:
  blender key_template.blend --background --python run_comp_key.py -- input.mp4 output.webm [params_json]

Expect the scene compositor to have these nodes (not inside a group):
  Movie Clip -> Keying -> Hue Saturation Value -> Group Output

The script swaps in the clip, applies keying/HSV params, and renders to WebM/VP9 with alpha.
"""
import bpy
import sys
import os
import json


def find_node(tree, bl_idname):
    """Return first node matching bl_idname."""
    return next((n for n in tree.nodes if n.bl_idname == bl_idname), None)


def set_attr(obj, name, value):
    """Safely set attribute if present."""
    if hasattr(obj, name):
        setattr(obj, name, value)


def set_input(node, socket, value):
    """Safely set node input default_value."""
    if socket in node.inputs:
        node.inputs[socket].default_value = value


def main():
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    if len(argv) < 2:
        print(
            "Usage: blender key_template.blend --background --python run_comp_key.py -- input.mp4 output.webm [params_json]"
        )
        sys.exit(1)

    input_path, output_path = argv[0], argv[1]
    params = {}
    if len(argv) >= 3:
        try:
            params = json.loads(argv[2])
        except Exception:
            print("⚠️ params JSON invalid; using defaults")

    # Defaults (can be overridden by params JSON)
    p = {
        "balance": params.get("balance", 0.5),
        "black_level": params.get("black_level", 0.0),
        "white_level": params.get("white_level", 0.86),
        "despill_factor": params.get("despill_factor", 1.0),
        "despill_balance": params.get("despill_balance", 0.5),
        "edge_kernel": params.get("edge_kernel", 3),
        "edge_tolerance": params.get("edge_tolerance", 0.1),
        "blur_pre": params.get("blur_pre", 0),
        "blur_post": params.get("blur_post", 0),
        "hue": params.get("hue", 0.5),
        "saturation": params.get("saturation", 1.0),
        "value": params.get("value", 1.0),
        "hsv_fac": params.get("hsv_fac", 1.0),
    }

    if not os.path.exists(input_path):
        print(f"❌ Input video not found: {input_path}")
        sys.exit(1)

    scene = bpy.context.scene
    # Blender 5.x: compositor node tree is on scene.compositor.node_tree
    tree = None
    comp = getattr(scene, "compositor", None)
    if comp:
        tree = getattr(comp, "node_tree", None)

    # If missing, create a compositor tree explicitly
    if not tree:
        try:
            new_tree = bpy.data.node_groups.new("CompositorNodeTree", "CompositorNodeTree")
            if comp:
                comp.node_tree = new_tree
                tree = comp.node_tree
        except Exception:
            tree = None

    if not tree:
        print("❌ No compositor node tree available. Please open the blend, go to Compositing, enable 'Use Nodes', and save.")
        sys.exit(1)

    # Ensure required nodes exist; if missing, create and link them
    movie = find_node(tree, "CompositorNodeMovieClip")
    key = find_node(tree, "CompositorNodeKeying")
    hsv = find_node(tree, "CompositorNodeHueSat")
    composite = find_node(tree, "CompositorNodeComposite")

    if not all([movie, key, hsv, composite]):
        # Clear and rebuild a minimal chain: Movie Clip -> Keying -> HSV -> Composite
        tree.nodes.clear()
        movie = tree.nodes.new("CompositorNodeMovieClip")
        key = tree.nodes.new("CompositorNodeKeying")
        hsv = tree.nodes.new("CompositorNodeHueSat")
        composite = tree.nodes.new("CompositorNodeComposite")

        # Layout positions (rough)
        movie.location = (-600, 0)
        key.location = (-300, 0)
        hsv.location = (0, 0)
        composite.location = (300, 0)

        links = tree.links
        links.new(movie.outputs.get("Image"), key.inputs.get("Image"))
        links.new(key.outputs.get("Image"), hsv.inputs.get("Image"))
        links.new(hsv.outputs.get("Image"), composite.inputs.get("Image"))

    # Load clip into Movie Clip node
    clip = bpy.data.movieclips.load(input_path)
    movie.clip = clip

    # Keying parameters
    set_attr(key, "balance", p["balance"])
    set_attr(key, "black_level", p["black_level"])
    set_attr(key, "white_level", p["white_level"])
    set_attr(key, "edge_kernel_radius", p["edge_kernel"])
    set_attr(key, "edge_kernel_tolerance", p["edge_tolerance"])
    set_attr(key, "despill_factor", p["despill_factor"])
    set_attr(key, "despill_balance", p["despill_balance"])
    set_attr(key, "blur_pre", p["blur_pre"])
    set_attr(key, "blur_post", p["blur_post"])

    # HSV parameters
    set_input(hsv, "Hue", p["hue"])
    set_input(hsv, "Saturation", p["saturation"])
    set_input(hsv, "Value", p["value"])
    set_input(hsv, "Fac", p["hsv_fac"])

    # Render settings derived from clip
    scene.render.resolution_x = clip.size[0]
    scene.render.resolution_y = clip.size[1]
    scene.render.resolution_percentage = 100
    scene.frame_start = 1
    scene.frame_end = clip.frame_duration
    scene.render.fps = int(clip.fps)
    scene.render.fps_base = 1.0

    # Output format: WebM VP9 RGBA
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "WEBM"
    scene.render.ffmpeg.codec = "VP9"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    scene.render.ffmpeg.audio_codec = "VORBIS"
    scene.render.ffmpeg.audio_bitrate = 192
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = output_path

    print(f"📥 Input: {input_path}")
    print(f"📤 Output: {output_path}")
    print(
        f"Keying params: balance={getattr(key,'balance','?')} black={getattr(key,'black_level','?')} white={getattr(key,'white_level','?')} "
        f"edge_size={getattr(key,'edge_kernel_radius','?')} tol={getattr(key,'edge_kernel_tolerance','?')} "
        f"despill={getattr(key,'despill_factor','?')} despill_bal={getattr(key,'despill_balance','?')}"
    )
    print(
        f"HSV: hue={p['hue']} sat={p['saturation']} val={p['value']} fac={p['hsv_fac']}"
    )
    print(
        f"Render: {scene.render.resolution_x}x{scene.render.resolution_y} @ {scene.render.fps}fps, frames {scene.frame_start}-{scene.frame_end}"
    )

    try:
        bpy.ops.render.render(animation=True, write_still=False)
    except Exception as exc:
        print(f"❌ Render failed: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if not os.path.exists(output_path):
        print("❌ Render completed but output file not found.")
        sys.exit(1)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"✅ Done. Output size: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
