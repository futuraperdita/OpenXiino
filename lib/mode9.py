"Compress a PIL image using Xiino mode 9."
import PIL.Image
import numpy as np
from lib.ebd_control_codes import CONTROL_CODES
from lib.xiino_palette_common import PALETTE


"""
Compress a PIL image using Xiino mode 9 with optimized color handling and compression.

The compression strategy uses several techniques to achieve better results while maintaining
client compatibility:

1. Color Space Optimization:
   - Uses LAB color space instead of RGB because LAB is perceptually uniform
   - This means that distances in LAB space better match human perception of color differences
   - Results in better color selection when reducing to the limited palette

2. Error Diffusion:
   - Implements Floyd-Steinberg dithering to maintain image quality
   - Works by spreading the quantization error to neighboring pixels
   - This creates patterns that are more compressible while preserving detail
   - Particularly effective for gradients and smooth color transitions

3. Pattern Matching:
   - Uses a sliding window approach to find repeating patterns
   - Limited to 32 pixels for performance while still catching most patterns
   - Weights different compression methods based on their efficiency:
     * RLE (Run Length Encoding) gets highest priority as it's most space-efficient
     * Vertical patterns get slight boost as they're common in web images
     * All while using only patterns the client can decompress
"""

def _rgb_to_lab_vectorized(rgb):
    """
    Convert RGB to LAB color space using vectorized NumPy operations.
    Takes either a single RGB tuple or a numpy array of RGB values.
    """
    rgb = np.asarray(rgb, dtype=np.float32)
    if rgb.ndim == 1:
        rgb = rgb.reshape(1, -1)
    
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
    
    # Compute f(t)
    mask = xyz > epsilon
    f = np.zeros_like(xyz)
    f[mask] = np.power(xyz[mask], 1/3)
    f[~mask] = (kappa * xyz[~mask] + 16) / 116
    
    # Compute LAB
    lab = np.zeros_like(xyz)
    lab[:, 0] = 116 * f[:, 1] - 16  # L
    lab[:, 1] = 500 * (f[:, 0] - f[:, 1])  # a
    lab[:, 2] = 200 * (f[:, 1] - f[:, 2])  # b
    
    return lab[0] if lab.shape[0] == 1 else lab

# Pre-compute LAB values for palette using vectorized conversion
PALETTE_ARRAY = np.array(PALETTE, dtype=np.float32)
PALETTE_LAB = [(i, lab) for i, lab in enumerate(_rgb_to_lab_vectorized(PALETTE_ARRAY))]

def find_closest_palette_index(pixel, x=0, y=0, error=None):
    """
    Find the closest matching color in our palette using vectorized LAB color space.
    Uses NumPy for efficient distance calculations.
    """
    r, g, b = pixel
    if error is not None:
        # Apply error diffusion
        r = max(0, min(255, int(r + error[0])))
        g = max(0, min(255, int(g + error[1])))
        b = max(0, min(255, int(b + error[2])))
    
    lab = _rgb_to_lab_vectorized((r, g, b))
    
    # Calculate distances
    lab_diffs = np.array([lab_color for _, lab_color in PALETTE_LAB]) - lab
    distances = np.sum(lab_diffs * lab_diffs, axis=1)
    best_index = np.argmin(distances)
    
    # Calculate quantization error for error diffusion
    if error is not None:
        selected_color = PALETTE[best_index]
        return best_index, (
            r - selected_color[0],
            g - selected_color[1],
            b - selected_color[2]
        )
    
    return best_index

def compress_mode9(image: PIL.Image.Image):
    """
    Compress an image using mode 9 compression with optimized color handling.
    
    The compression process works in two main phases:
    
    1. Translate color space, optimize image using Floyd-Steinberg dithering
    2. Compression / Pattern-Matching phase
    """
    # Convert to RGB to ensure consistent color format
    image = image.convert("RGB")
    
    # Initialize error buffer for Floyd-Steinberg dithering
    width, height = image.size
    error_buffer = [[None] * width for _ in range(height)]
    
    data = list(image.getdata())
    rows = []
    buffer = bytearray()
    
    # Implement Floyd-Steinberg dithering on image data
    for y in range(height):
        row_data = []
        for x in range(width):
            pixel = data[y * width + x]
            # Get error from previous pixels if any
            error = error_buffer[y][x] if error_buffer[y][x] is not None else (0, 0, 0)
            
            # Find closest color and get quantization error
            color_index, quant_error = find_closest_palette_index(pixel, x, y, error)
            row_data.append(pixel)  # Store original pixel for compression
            
            # Distribute error
            if x < width - 1:
                error_buffer[y][x + 1] = tuple(e * 7/16 for e in quant_error) if error_buffer[y][x + 1] is None else \
                    tuple(e1 + e2 * 7/16 for e1, e2 in zip(error_buffer[y][x + 1], quant_error))
            if y < height - 1:
                if x > 0:
                    error_buffer[y + 1][x - 1] = tuple(e * 3/16 for e in quant_error) if error_buffer[y + 1][x - 1] is None else \
                        tuple(e1 + e2 * 3/16 for e1, e2 in zip(error_buffer[y + 1][x - 1], quant_error))
                error_buffer[y + 1][x] = tuple(e * 5/16 for e in quant_error) if error_buffer[y + 1][x] is None else \
                    tuple(e1 + e2 * 5/16 for e1, e2 in zip(error_buffer[y + 1][x], quant_error))
                if x < width - 1:
                    error_buffer[y + 1][x + 1] = tuple(e * 1/16 for e in quant_error) if error_buffer[y + 1][x + 1] is None else \
                        tuple(e1 + e2 * 1/16 for e1, e2 in zip(error_buffer[y + 1][x + 1], quant_error))
        
        rows.append(row_data)
    
    # Compress rows with enhanced pattern matching
    for index, row in enumerate(rows):
        if index == 0:
            buffer.extend(compress_line(row, None, True))
        else:
            buffer.extend(compress_line(row, rows[index - 1], False))
    
    return bytes(buffer)


def compress_line(line: list, prev_line: list | None, first_line: bool):
    """
    Compress a single line of image data using pattern matching and RLE.
    
    The compression uses two main strategies in order of preference:
    
    1. RLE (Run Length Encoding)
    2. Pattern Matching
    
    All compression methods use control codes that are compatible with
    the original client, ensuring the compressed data can be decoded.
    """
    active_colour = 0x00
    buffer = bytearray()
    
    index = 0
    while index < len(line):
        pixel = line[index]
        
        # Initialize pattern matching lengths
        lb_copy_length_a = 0  # offset -1
        lb_copy_length_b = 0  # offset 0
        lb_copy_length_c = 0  # offset 1
        
        if not first_line:
            # Align sliding window to cacheline
            window_size = min(21, len(line) - index)
            
            # Standard lookback patterns
            if index > 0:
                while (index + lb_copy_length_a < len(line) and
                       index - 1 + lb_copy_length_a < len(prev_line) and
                       line[index + lb_copy_length_a] == prev_line[index - 1 + lb_copy_length_a]):
                    lb_copy_length_a += 1
                    if lb_copy_length_a >= window_size:
                        break
            
            while (index + lb_copy_length_b < len(line) and
                   index + lb_copy_length_b < len(prev_line) and
                   line[index + lb_copy_length_b] == prev_line[index + lb_copy_length_b]):
                lb_copy_length_b += 1
                if lb_copy_length_b >= window_size:
                    break
            
            if index + 1 < len(prev_line):
                while (index + lb_copy_length_c < len(line) and
                       index + 1 + lb_copy_length_c < len(prev_line) and
                       line[index + lb_copy_length_c] == prev_line[index + 1 + lb_copy_length_c]):
                    lb_copy_length_c += 1
                    if lb_copy_length_c >= window_size:
                        break

        # Method 2: RLE compression
        if index + 1 > len(line) - 1:
            # bail here! we'll except if we try to check RLE viability!
            rle_length = 0
        elif line[index + 1] != pixel:
            # RLE does not apply here
            rle_length = 0
        else:
            rle_length = 0
            while (
                index + rle_length < len(line)
                and line[index + rle_length] == pixel
            ):
                rle_length += 1

        # Compare compression methods (RLE, lookback)
        # Weight the compression methods while maintaining client compatibility
        compare_dict = {
            "rle": rle_length * 1.2,  # Prefer RLE slightly
            "lb_-1": lb_copy_length_a,
            "lb_0": lb_copy_length_b * 1.1,  # Slight preference for vertical patterns
            "lb_1": lb_copy_length_c
        }
        best_compression = max(compare_dict, key=compare_dict.get)
        # Convert back to original method names for control code lookup
        best_compression = best_compression.split('*')[0].strip()

        if all(value == 0 for value in compare_dict.values()):
            # data can't be compressed
            # rle not applicable
            # and does not appear anywhere on previous line
            # just write the colour to the buffer
            active_colour = find_closest_palette_index(pixel)
            buffer.append(active_colour)
        # HACK force RLE
        elif best_compression == "rle":
            active_colour = find_closest_palette_index(pixel)
            buffer.append(active_colour)

            if rle_length >= 6:
                # RLE beyond 6 uses 6's code and a length
                buffer.append(CONTROL_CODES["RLE_6"])
                buffer.append(rle_length - 6)
            else:
                buffer.append(CONTROL_CODES[f"RLE_{rle_length}"])

            index += rle_length

        elif best_compression == "lb_-1":
            if 1 <= lb_copy_length_a <= 5:
                buffer.append(CONTROL_CODES[f"COPY_{lb_copy_length_a}_OFFSET_-1"])
            else:
                buffer.append(CONTROL_CODES["COPY_6_OFFSET_-1"])
                buffer.append(lb_copy_length_a - 6)
            index += lb_copy_length_a - 1

        elif best_compression == "lb_0":
            if 1 <= lb_copy_length_b <= 5:
                buffer.append(CONTROL_CODES[f"COPY_{lb_copy_length_b}_OFFSET_0"])
            else:
                buffer.append(CONTROL_CODES["COPY_6_OFFSET_0"])
                buffer.append(lb_copy_length_b - 6)
            index += lb_copy_length_b - 1

        elif best_compression == "lb_1":
            if 1 <= lb_copy_length_c <= 5:
                buffer.append(CONTROL_CODES[f"COPY_{lb_copy_length_c}_OFFSET_1"])
            else:
                buffer.append(CONTROL_CODES["COPY_6_OFFSET_1"])
                buffer.append(lb_copy_length_c - 6)
            index += lb_copy_length_c - 1

        index += 1

    return bytes(buffer)
