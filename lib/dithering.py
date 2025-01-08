"""Dithering algorithms for image processing."""
import os
import numpy as np
from typing import Tuple
from lib.logger import image_logger

# 4x4 Bayer matrix for ordered dithering
BAYER_MATRIX_4x4 = np.array([
    [ 0, 8, 2,10],
    [12, 4,14, 6],
    [ 3,11, 1, 9],
    [15, 7,13, 5]
], dtype=np.float32) / 16.0

def apply_floyd_steinberg_dithering(
    data: np.ndarray,
    find_closest_color_fn
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply Floyd-Steinberg dithering to image data.
    
    Args:
        data: Image data as numpy array (height, width, channels)
        find_closest_color_fn: Function that takes a pixel and returns (index, error)
    
    Returns:
        Tuple of (processed data, indices)
    """
    height, width = data.shape[:2]
    image_logger.debug(f"Starting Floyd-Steinberg dithering ({width}x{height})")
    
    error_buffer = np.zeros_like(data, dtype=np.float32)
    processed_data = np.zeros_like(data)
    indices = np.zeros((height, width), dtype=np.uint8)
    
    total_error = 0.0
    
    for y in range(height):
        row_data = data[y].copy()
        # Apply accumulated error
        row_with_error = np.clip(row_data + error_buffer[y], 0, 255)
        
        # Find closest colors and get errors
        row_indices, quant_errors = find_closest_color_fn(row_with_error)
        indices[y] = row_indices
        
        # Track error statistics
        row_error = np.abs(quant_errors).mean()
        total_error += row_error
        
        if y % 50 == 0 and y > 0:  # Log progress less frequently
            avg_error = total_error / (y + 1)
            image_logger.debug(f"Progress: {y}/{height} rows processed (avg error={avg_error:.2f})")
        
        # Get the actual quantized colors for this row
        selected_colors = PALETTE_ARRAY[row_indices]
        # Handle both RGB and grayscale data
        if len(data.shape) == 2:  # Grayscale
            processed_data[y] = selected_colors.mean(axis=1) if selected_colors.ndim > 1 else selected_colors
        else:  # RGB
            processed_data[y] = selected_colors
        
        # Distribute error (Floyd-Steinberg)
        if y < height - 1:
            # Right pixel (7/16)
            error_buffer[y, 1:] += quant_errors[:-1] * 7/16
            # Bottom-left pixel (3/16)
            error_buffer[y+1, :-1] += quant_errors[1:] * 3/16
            # Bottom pixel (5/16)
            error_buffer[y+1, :] += quant_errors * 5/16
            # Bottom-right pixel (1/16)
            if width > 1:
                error_buffer[y+1, 1:] += quant_errors[:-1] * 1/16
    
    final_error = total_error / height
    image_logger.debug(f"Dithering complete (avg error={final_error:.2f})")
    return processed_data, indices

def apply_ordered_dithering(
    data: np.ndarray,
    find_closest_color_fn
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply ordered dithering using 4x4 Bayer matrix.
    
    Args:
        data: Image data as numpy array (height, width, channels)
        find_closest_color_fn: Function that takes a pixel and returns (index, error)
    
    Returns:
        Tuple of (processed data, indices)
    """
    height, width = data.shape[:2]
    image_logger.debug(f"Starting ordered dithering ({width}x{height}, {'RGB' if len(data.shape) == 3 else 'grayscale'})")
    
    # Tile the Bayer matrix to match image size
    threshold_map = np.tile(BAYER_MATRIX_4x4, ((height + 3) // 4, (width + 3) // 4))[:height, :width]
    
    # Add threshold map to each color channel and scale appropriately
    if len(data.shape) == 3:  # RGB data
        data_with_threshold = data + threshold_map[:, :, np.newaxis] * 32 - 16
    else:  # Grayscale data
        data_with_threshold = data + threshold_map * 32 - 16
    data_with_threshold = np.clip(data_with_threshold, 0, 255)
    
    # Find closest colors for all pixels at once
    if len(data.shape) == 3:  # RGB data
        data_flat = data_with_threshold.reshape(-1, 3)
    else:  # Grayscale data
        data_flat = data_with_threshold.reshape(-1)
        
    indices, errors = find_closest_color_fn(data_flat)
    indices = indices.reshape(height, width).astype(np.uint8)
    
    # Calculate and log final error
    final_error = np.abs(errors).mean()
    image_logger.debug(f"Dithering complete (avg error={final_error:.2f})")
    
    # Get the actual quantized colors for all pixels
    processed_data = np.zeros_like(data)
    if len(data.shape) == 3:  # RGB data
        processed_data = processed_data.reshape(-1, 3)
        processed_data[:] = PALETTE_ARRAY[indices.flatten()]
        processed_data = processed_data.reshape(data.shape)
    else:  # Grayscale data
        processed_data = processed_data.reshape(-1)
        selected_colors = PALETTE_ARRAY[indices.flatten()]
        processed_data[:] = selected_colors.mean(axis=1) if selected_colors.ndim > 1 else selected_colors
        processed_data = processed_data.reshape(data.shape)
    
    image_logger.debug("Ordered dithering complete")
    return processed_data, indices

def apply_dithering(
    data: np.ndarray,
    find_closest_color_fn,
    priority: str = None,
    palette_array: np.ndarray = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply dithering based on priority setting.
    
    Args:
        data: Image data as numpy array (height, width, channels)
        find_closest_color_fn: Function that takes pixels and returns (indices, errors)
        priority: Optional priority override, otherwise uses IMAGE_DITHER_PRIORITY env var
    
    Returns:
        Tuple of (processed data, indices)
    """
    # Ensure we have a palette array for quantization
    if palette_array is None:
        from lib.xiino_palette_common import PALETTE
        palette_array = np.array(PALETTE, dtype=np.float32)
    
    # Set global for dithering functions to use
    global PALETTE_ARRAY
    PALETTE_ARRAY = palette_array
    
    if priority is None:
        priority = os.environ.get('IMAGE_DITHER_PRIORITY', 'quality')
    
    image_logger.debug(f"Starting dithering (priority={priority}, shape={data.shape}, palette={len(palette_array)} colors)")
    
    if priority == 'performance':
        return apply_ordered_dithering(data, find_closest_color_fn)
    else:  # 'quality'
        return apply_floyd_steinberg_dithering(data, find_closest_color_fn)
