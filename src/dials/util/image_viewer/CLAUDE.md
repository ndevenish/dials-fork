# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this directory.

## Overview

The DIALS image viewer (`dials.image_viewer`) is a wxPython GUI for viewing diffraction images with overlays for spot finding, indexing, and integration results. It adapts a "slippy map" tiled rendering approach (originally from OpenStreetMap) for efficient display of large detector images.

## Entry Point

`src/dials/command_line/image_viewer.py` defines the CLI (`dials.image_viewer`), parses PHIL parameters, and calls `spot_wrapper.display()` from `spotfinder_wrap.py`.

```
dials.image_viewer image.cbf
dials.image_viewer models.expt strong.refl
```

## File Map

### Top-level files

- **`__init__.py`** — Exports `calculate_isoresolution_lines()` for drawing resolution rings
- **`spotfinder_wrap.py`** — `spot_wrapper` class: creates wx.App, instantiates SpotFrame, populates image chooser, runs event loop. Also handles optional ZMQ endpoint for remote image delivery
- **`spotfinder_frame.py`** — `SpotFrame` (extends slip_viewer's `XrayFrame`): the primary viewer window. Handles DIALS experiments/reflections, spot/prediction overlays, masking, threshold visualization, image stacking
- **`rstbx_frame.py`** — Legacy `XrayFrame` base class from rstbx
- **`viewer_tools.py`** — GUI utilities: `ImageCollectionWithSelection` (manages loaded images), `LegacyChooserAdapter` (wx.Choice-like API wrapper), toolbar controls, event types
- **`mask_frame.py`** — `MaskSettingsFrame` (wx.MiniFrame): UI for creating masks with rectangles, circles, polygons, resolution ranges, ice rings, and border pixels

### `slip_viewer/` subdirectory (core rendering)

- **`pyslip.py`** (~2900 lines) — `PySlip` widget: tiled map renderer with zoom levels -3 to 5, layer-based overlay system, coordinate conversions (view/geo/map/image), pan/zoom interaction
- **`frame.py`** — `XrayFrame`: main viewer frame (menus, toolbar, statusbar, settings). Extends `rstbx_frame.XrayFrame` and hosts the PySlip canvas
- **`tile_generation.py`** — `_Tiles`: image data management, brightness/color scheme application, tile caching (LRU, 512 tiles per zoom level)
- **`flex_image.py`** — `get_flex_image_multipanel()`: pads multi-panel detector data into a uniform FlexImage for rendering
- **`slip_viewer_image_factory.py`** — Image loading factory
- **`calibration_frame.py`** — CSPAD quad translation/calibration UI
- **`ring_frame.py`** — Reciprocal space ring overlay controls
- **`uc_frame.py`** — Unit cell / Miller indices visualization
- **`line_frame.py`** — Line profile tool (matplotlib integration)
- **`ellipse_frame.py`** — Ellipse fitting tool (uses scikit-image EllipseModel)
- **`score_frame.py`** — Image scoring/rating interface
- **`rotate_detector.py`** — Detector rotation utilities

## Class Hierarchy

```
rstbx_frame.XrayFrame (legacy base)
  └── slip_viewer/frame.XrayFrame (menus, toolbar, pyslip canvas, tool frames)
        └── spotfinder_frame.SpotFrame (DIALS experiments/reflections, overlays)
```

Tool windows (`wx.MiniFrame`): MaskSettingsFrame, RingSettingsFrame, UCSettingsFrame, ScoreSettingsFrame, LineSettingsFrame, EllipseSettingsFrame, SBSettingsFrame (calibration)

## Image Data Pipeline

1. User selects image via toolbar chooser
2. `load_image(chooser_wrapper)` creates image object from detector data
3. `tile_generation._Tiles.set_image()` loads raw data, creates `FlexImage_d` from multi-panel geometry, applies brightness/color
4. PySlip renders 256x256 tiles at current zoom level with LRU caching
5. Overlay layers (spots, predictions, rings, masks, beam center, Miller indices) drawn on top

## PySlip Layer System

Overlays are managed as named layers:
- `AddPolygonLayer()` — rings, masks, beam center crosshair, tile boundaries
- `AddEllipseLayer()` — fitted reflection ellipses
- `AddPointLayer()` — spot centroids, predictions
- `AddTextLayer()` — resolution labels, Miller indices
- Each layer has visibility, selectability, show_levels, and style attributes

## Coordinate Systems

Multiple coordinate spaces with explicit conversion methods:
- **Image pixel** — detector readout coordinates
- **Picture** — multi-panel projected coordinates
- **Map-relative** — PySlip internal coordinates
- **View** — screen pixel coordinates

## Plugin System

Files matching `*_frame_plugin.py` in `slip_viewer/` are dynamically loaded at startup via `SourceFileLoader`. Each plugin gets a menu item and can create custom tool frames.

## Key Dependencies

- **wxPython** — GUI framework
- **wxtbx** — wx extensions (controls, bitmaps, phil_controls)
- **iotbx.detectors** — Image I/O, FlexImage creation
- **dxtbx** — Detector geometry model
- **cctbx** — Crystallographic calculations
- **rstbx.viewer** — Legacy viewer infrastructure
- **matplotlib** — Line profile plotting
- **scikit-image** — Ellipse fitting
- **zmq** (optional) — Remote image streaming via ZMQ PULL socket

## Brightness Rendering

The brightness slider (1-1000, default 10) controls a `correction` multiplier that maps raw pixel values into a 0-255 display range. The C++ implementation lives in `iotbx/detectors/display.h` (in the cctbx_project repo, not this one).

### Computing the correction factor

The `correction` is auto-scaled to the image content so that the brightness slider has consistent perceptual effect across different images:

- **Single-panel** (`FlexImage` constructor → `global_bright_contrast()`): collects active-area pixels, uses `std::nth_element` to find the 90th percentile value, then `correction = brightness * 0.4 / p90`
- **Multi-panel** (`generic_flex_image` → `followup_brightness_scale()`): computes mean, builds a 100-bin histogram, walks it to find the 90th percentile, same formula: `correction = brightness * 0.4 / p90`

### Pixel value mapping (`bright_contrast()`)

For each pixel: `outvalue = 256 * (1.0 - pixel * correction)`, clamped to [0, 255]. This is an inverted mapping — higher raw values produce lower output values. Special sentinel values bypass this: `-2` (Pilatus inactive) and `INT_MIN` (masked) → flag 1000, above saturation → flag 2000.

### Color scheme application (`adjust()`)

After `bright_contrast()` produces 0-255 values, `adjust()` maps to RGB:
- **Grayscale**: value used directly
- **Invert**: `255 - value`
- **Rainbow**: HSV with `h = 255 * sqrt(value/255)`
- **Heatmap**: `ratio = ((255-value)/255)²` → heatmap color
- Flag 1000 (inactive/masked) → red in grayscale, black in rainbow/heatmap
- Flag 2000 (saturated) → yellow in grayscale, white in rainbow, green in heatmap

### Python-side flow

1. Slider/text control fires `OnUpdateBrightness` in `spotfinder_frame.py` → sets `settings.brightness`
2. `update_settings()` detects change, calls `tiles.update_brightness(b, color_scheme)` in `tile_generation.py`
3. `update_brightness()` rebuilds the FlexImage with `brightness=b/100`, flushes the tile cache, calls `adjust()`
4. PySlip re-renders all visible tiles from the new FlexImage

## Notable Design Decisions

- **Tiled rendering**: PySlip breaks detector images into 256x256 tiles at multiple zoom levels, enabling smooth pan/zoom of very large images
- **Lazy PySlip init on Linux**: PySlip creation is deferred on X11 due to async window creation issues
- **LegacyChooserAdapter**: Wraps `ImageCollectionWithSelection` with a wx.Choice-like API so upstream rstbx code works unchanged
- **Multi-panel padding**: `get_flex_image_multipanel()` pads panels to uniform size in a single flex array for rendering across different detector geometries
- **Mask sentinel value**: `MASK_VAL = -(2^31)` in int32 marks masked pixels
