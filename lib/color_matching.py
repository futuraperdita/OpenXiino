"""Color matching and conversion utilities."""
import numpy as np
from typing import Tuple
from lib.xiino_palette_common import PALETTE
from lib.logger import image_logger

def rgb_to_lab_vectorized(rgb):
    """
    Convert RGB to LAB color space using vectorized NumPy operations.
    Takes either a single RGB tuple or a numpy array of RGB values.
    Handles edge cases and ensures valid input ranges.
    """
    rgb = np.asarray(rgb, dtype=np.float32)
    if rgb.ndim == 1:
        rgb = rgb.reshape(1, -1)
    
    # Ensure RGB values are in valid range
    rgb = np.clip(rgb, 0, 255)
    
    # Normalize RGB values
    rgb = rgb / 255.0
    
    # RGB to XYZ matrix (D65 illuminant)
    xyz_matrix = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041]
    ], dtype=np.float32)
    
    # Convert to XYZ
    xyz = np.dot(rgb, xyz_matrix.T)
    
    # XYZ to LAB
    epsilon = 0.008856
    kappa = 903.3
    
    # Reference white point (D65)
    xn, yn, zn = 0.95047, 1.0, 1.08883
    xyz = xyz / [xn, yn, zn]
    
    # Handle numerical instability
    xyz = np.maximum(xyz, 1e-6)
    
    # Compute f(t)
    mask = xyz > epsilon
    f = np.zeros_like(xyz)
    f[mask] = np.power(xyz[mask], 1/3)
    f[~mask] = (kappa * xyz[~mask] + 16) / 116
    
    # Compute LAB
    lab = np.zeros_like(xyz)
    lab[:, 0] = np.maximum(0, 116 * f[:, 1] - 16)  # L (0 to 100)
    lab[:, 1] = 500 * (f[:, 0] - f[:, 1])  # a
    lab[:, 2] = 200 * (f[:, 1] - f[:, 2])  # b
    
    return lab[0] if lab.shape[0] == 1 else lab

def create_gray_palette(levels: int) -> np.ndarray:
    """Create a grayscale palette with perceptually uniform steps in LAB space."""
    image_logger.debug(f"Creating {levels}-level grayscale palette")
    
    # Create evenly spaced L values (perceptual brightness)
    l_values = np.linspace(0, 100, levels)
    # Create LAB colors with a=b=0 (neutral gray)
    lab_colors = np.zeros((levels, 3), dtype=np.float32)
    lab_colors[:, 0] = l_values
    
    # Convert LAB to RGB for error calculation
    rgb_colors = np.zeros((levels, 3), dtype=np.float32)
    for i, l in enumerate(l_values):
        # Convert L value to XYZ
        y = ((l + 16) / 116) ** 3 if l > 8 else l / 903.3
        # Convert XYZ to RGB (simplified since x=z=y for neutral gray)
        rgb = np.dot(np.array([y, y, y]), np.linalg.inv(np.array([
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041]
        ])))
        rgb_colors[i] = np.clip(rgb * 255, 0, 255)
    
    image_logger.debug(f"Created grayscale palette with {levels} levels")
    return rgb_colors

# Pre-compute palette arrays for color and grayscale matching
PALETTE_ARRAY = np.array(PALETTE, dtype=np.float32)
PALETTE_LAB = rgb_to_lab_vectorized(PALETTE_ARRAY)

# Pre-compute grayscale palettes (2-bit and 4-bit)
GRAY_PALETTE_2BIT = create_gray_palette(4)  # 4 levels for 2-bit
GRAY_PALETTE_4BIT = create_gray_palette(16)  # 16 levels for 4-bit
GRAY_PALETTE_LAB_2BIT = rgb_to_lab_vectorized(GRAY_PALETTE_2BIT)[:, 0]  # L values only
GRAY_PALETTE_LAB_4BIT = rgb_to_lab_vectorized(GRAY_PALETTE_4BIT)[:, 0]  # L values only

def find_closest_color(pixels: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Find closest palette colors for RGB pixels using LAB color space."""
    pixels = np.asarray(pixels, dtype=np.float32)
    if pixels.ndim == 1:
        pixels = pixels.reshape(1, 3)
    
    num_pixels = len(pixels)
    image_logger.debug(f"Finding closest colors for {num_pixels} pixels")
    
    # Convert input pixels to LAB
    pixels_lab = rgb_to_lab_vectorized(pixels)
    
    # Reshape arrays for broadcasting
    pixels_lab = pixels_lab.reshape(-1, 1, 3)  # Shape: (N, 1, 3)
    palette_lab = PALETTE_LAB.reshape(1, -1, 3)  # Shape: (1, P, 3)
    
    # Calculate distances to all palette colors at once
    diff = pixels_lab - palette_lab
    distances = np.sum(diff * diff, axis=2)  # Sum along color channels
    indices = np.argmin(distances, axis=1)
    
    # Calculate quantization errors in RGB space
    selected_colors = PALETTE_ARRAY[indices]
    errors = pixels - selected_colors
    
    # Calculate error statistics
    avg_error = np.abs(errors).mean()
    max_error = np.abs(errors).max()
    unique_colors = len(np.unique(indices))
    image_logger.debug(f"Color quantization: avg error={avg_error:.2f}, max error={max_error:.2f}, unique colors={unique_colors}")
    
    return indices, errors

def find_closest_gray(pixels: np.ndarray, levels: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Find closest grayscale values for pixels using LAB color space.
    LAB's L component represents perceived lightness better than RGB.
    Uses pre-computed LAB palettes for better performance.
    """
    pixels = np.asarray(pixels, dtype=np.float32)
    if pixels.ndim == 1:
        pixels = pixels.reshape(-1, 1)
    
    num_pixels = len(pixels)
    image_logger.debug(f"Finding closest {levels}-level grayscale values for {num_pixels} pixels")
    
    # Convert RGB to LAB if needed
    if len(pixels.shape) > 1 and pixels.shape[-1] == 3:
        image_logger.debug("Converting RGB input to LAB space")
        pixels_lab = rgb_to_lab_vectorized(pixels)
        # Use only L component (perceived lightness)
        pixels = pixels_lab[:, 0]  # L ranges from 0 to 100
    else:
        # If already grayscale, convert to L scale (0-100)
        pixels = pixels * (100/255)
    
    # Use pre-computed palette based on bit depth
    if levels == 4:  # 2-bit
        gray_palette_lab = GRAY_PALETTE_LAB_2BIT
    elif levels == 16:  # 4-bit
        gray_palette_lab = GRAY_PALETTE_LAB_4BIT
    else:
        raise ValueError(f"Unsupported grayscale levels: {levels}")
    
    # Find closest L values
    pixels = pixels.reshape(-1, 1)
    diffs = np.abs(pixels - gray_palette_lab.reshape(1, -1))
    indices = np.argmin(diffs, axis=1)
    
    # Calculate errors in LAB space for better perceptual accuracy
    selected_l = gray_palette_lab[indices]
    errors = pixels.flatten() - selected_l
    
    # Calculate error statistics
    avg_error = np.abs(errors).mean()
    max_error = np.abs(errors).max()
    unique_levels = len(np.unique(indices))
    image_logger.debug(f"Grayscale quantization: avg error={avg_error:.2f}, max error={max_error:.2f}, unique levels={unique_levels}/{levels}")
    
    # Invert indices for Xiino's format (0 = white, max = black)
    quantized = ((levels - 1) - indices).astype(np.uint8)
    
    return quantized, errors * (255/100)  # Scale errors back to RGB range
