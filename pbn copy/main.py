from pbn.config import PipelineConfig, parse_args
from pbn.io import ensure_dir, load_rgb_image, save_json, save_png
from pbn.preprocess import preprocess_image
from pbn.edges import build_edge_strength_map
from pbn.superpixels import compute_superpixels
from pbn.palette import build_palette_from_superpixels, assign_superpixels_to_palette, make_palette_records
from pbn.merge import build_importance_map, safe_merge_tiny_regions
from pbn.render import (
    build_final_label_map,
    cleanup_label_map,
    labels_to_preview,
    render_lines_and_numbers,
    render_palette_image,
    extract_region_metadata,
)
from pbn.pdf_export import export_pdf, PAPER_SIZES_WITH_BLEED_CM


def run(config: PipelineConfig) -> None:
    ensure_dir(config.out_dir)
    print(
        f"Settings: colors={config.colors}, size={config.size}, detail_level={config.detail_level:.2f}, "
        f"superpixel_area_px={config.superpixel_area_px}, superpixel_shape={config.superpixel_shape}, "
        f"superpixels=[{config.superpixels_min},{config.superpixels_max}], "
        f"edge_threshold={config.edge_threshold:.3f}, lab_merge_threshold={config.lab_merge_threshold:.2f}"
    )

    print("[1/8] Loading + preprocessing image")
    image_rgb = load_rgb_image(config.input_path)
    prep = preprocess_image(image_rgb, config)

    print("[2/8] Building edge map")
    edge_strength = build_edge_strength_map(prep.edge_source_rgb)

    print("[3/8] Superpixel segmentation")
    sp_data = compute_superpixels(prep.rgb, prep.lab, edge_strength, config)

    print("[4/8] Palette clustering + initial assignment")
    palette = build_palette_from_superpixels(sp_data, config)
    sp_color_labels = assign_superpixels_to_palette(sp_data.mean_lab, palette.lab)

    print("[5/8] Importance map + safe region merging")
    importance_map = build_importance_map(prep.rgb, edge_strength, config.importance_mask_path)
    min_region_area_px = config.resolve_default_min_region_area(prep.rgb.shape[1], prep.rgb.shape[0])
    merged_labels = safe_merge_tiny_regions(
        sp_data=sp_data,
        palette=palette,
        initial_sp_color_labels=sp_color_labels,
        edge_strength=edge_strength,
        importance_map=importance_map,
        config=config,
    )

    print("[6/8] Raster cleanup + previews")
    final_label_map = build_final_label_map(sp_data.labels, merged_labels)
    final_label_map = cleanup_label_map(final_label_map, passes=config.cleanup_passes)
    preview = labels_to_preview(final_label_map, palette.rgb)

    print("[7/8] Line art + numbers + metadata")
    line_img, region_infos = render_lines_and_numbers(
        label_map=final_label_map,
        line_width=config.line_width,
        min_number_area=config.resolve_default_min_number_area(min_region_area_px),
    )
    regions_json = extract_region_metadata(region_infos, final_label_map)

    print("[8/8] Saving outputs")
    save_png(config.out_dir / "preview_color.png", preview)
    save_png(config.out_dir / "pbn_lines.png", line_img)
    save_png(config.out_dir / "palette.png", render_palette_image(palette.rgb, swatch_width=270, swatch_height=88))
    save_json(config.out_dir / "palette.json", make_palette_records(palette.lab, palette.rgb))
    save_json(config.out_dir / "regions.json", regions_json)

    if config.export_pdf:
        export_pdf(
            out_path=config.out_dir / "paint_by_numbers.pdf",
            lines_image_path=config.out_dir / "pbn_lines.png",
            palette_records=make_palette_records(palette.lab, palette.rgb),
            print_format=config.print_format,
        )

    print(f"Done. Output folder: {config.out_dir}")


if __name__ == "__main__":
    run(parse_args())
