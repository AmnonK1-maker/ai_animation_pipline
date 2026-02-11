"""Blender 4.2 keying script (matches your working setup).

Called by blender_server.py via:
    blender --background --python blender_keying.py -- input.mp4 output.webm [params_json]
"""

import bpy
import os
import sys
import json


def set_val(node, names, val):
    if isinstance(names, str):
        names = [names]
    for name in names:
        if name in node.inputs:
            node.inputs[name].default_value = val
            break


def setup_and_render(input_path, output_path, params):
    print(f"--- STARTING BLENDER 4.2 JOB: {os.path.basename(input_path)} ---")

    scene = bpy.context.scene
    scene.use_nodes = True

    # Color management for consistent output
    if hasattr(scene.view_settings, "view_transform"):
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"

    tree = scene.node_tree
    tree.nodes.clear()
    tree.links.clear()

    # Load video & sync FPS
    node_movie = tree.nodes.new(type="CompositorNodeMovieClip")
    node_movie.location = (-600, 0)
    try:
        clip = bpy.data.movieclips.load(input_path)
        node_movie.clip = clip
        fps = clip.fps
        scene.render.fps = int(round(fps))
        scene.render.fps_base = 1.0 if fps % 1 == 0 else 1.001
        scene.frame_start = 1
        scene.frame_end = clip.frame_duration
        scene.render.resolution_x = clip.size[0]
        scene.render.resolution_y = clip.size[1]
        print(f"Detected FPS: {fps}. Output set to match.")
    except Exception as e:
        print(f"Error loading clip: {e}")
        sys.exit(1)

    # Keying settings (from params or defaults)
    key_color = params.get("key_color", "green").lower()
    key_rgba = params.get("key_rgba")
    if key_rgba and isinstance(key_rgba, (list, tuple)) and len(key_rgba) == 4:
        key_color_rgba = tuple(key_rgba)
    else:
        key_color_rgba = (0.0, 0.837, 0.0, 1.0) if key_color == "green" else (0.0, 0.0, 1.0, 1.0)

    clip_white = params.get("clip_white", 0.887)
    saturation = params.get("saturation", 1.5)
    curve_x = params.get("curve_x", 0.6)
    curve_y = params.get("curve_y", 0.7)

    node_keying = tree.nodes.new(type="CompositorNodeKeying")
    node_keying.location = (-300, 0)
    set_val(node_keying, ["Key Color", "Key"], key_color_rgba)
    set_val(node_keying, ["Clip White", "White Level", "White"], clip_white)
    set_val(node_keying, ["Clip Black", "Black Level", "Black"], 0.0)

    node_hsv = tree.nodes.new(type="CompositorNodeHueSat")
    node_hsv.location = (0, 0)
    set_val(node_hsv, ["Saturation", "Sat"], saturation)

    node_curve = tree.nodes.new(type="CompositorNodeCurveRGB")
    node_curve.location = (300, 0)
    # Add curve point safely
    try:
        curve = node_curve.mapping.curves[3]
        new_point = curve.points.new(curve_x, curve_y)
        node_curve.mapping.update()
    except Exception as e:
        print(f"Warning: Could not add curve point: {e}")

    node_output = tree.nodes.new(type="CompositorNodeComposite")
    node_output.location = (600, 0)

    # Link nodes
    links = tree.links
    links.new(node_movie.outputs[0], node_keying.inputs[0])
    links.new(node_keying.outputs[0], node_hsv.inputs[0])
    links.new(node_hsv.outputs[0], node_curve.inputs[0])
    links.new(node_curve.outputs[0], node_output.inputs[0])

    # Render settings
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "WEBM"
    scene.render.ffmpeg.codec = "WEBM"
    # VP9 CRF: 0-63 (lower = better quality, 15 = very high quality)
    scene.render.ffmpeg.constant_rate_factor = str(params.get("crf", 15))
    scene.render.ffmpeg.gopsize = params.get("gopsize", 18)
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"

    # Memory protection (optional)
    scene.render.threads_mode = "FIXED"
    scene.render.threads = int(params.get("threads", 4))

    # For FFMPEG/WebM, use the full path with extension
    scene.render.filepath = output_path
    print(f"Render Target: {output_path}")
    
    try:
        bpy.ops.render.render(animation=True)
        print(f"✅ Render completed")
        
        # Check if output exists
        if os.path.exists(output_path):
            print(f"✅ Output file found: {output_path}")
        else:
            # List files in temp directory to debug
            temp_dir = os.path.dirname(output_path)
            if os.path.exists(temp_dir):
                files = os.listdir(temp_dir)
                print(f"❌ Output not found. Files in {temp_dir}: {files}")
            else:
                print(f"❌ Temp directory doesn't exist: {temp_dir}")
    except Exception as e:
        print(f"❌ Render failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    if len(argv) < 2:
        print("Usage: blender --background --python blender_keying.py -- input.mp4 output.webm [params_json]")
        sys.exit(1)

    input_path, output_path = argv[0], argv[1]
    params = {}
    if len(argv) >= 3:
        try:
            params = json.loads(argv[2])
        except Exception:
            print("⚠️ params JSON invalid; using defaults")

    setup_and_render(input_path, output_path, params)


if __name__ == "__main__":
    main()
