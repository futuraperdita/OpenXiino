"""Compress a PIL image using Xiino mode 9."""
import PIL.Image
import numpy as np
from lib.ebd_control_codes import CONTROL_CODES
from lib.color_matching import find_closest_color
from lib.dithering import apply_dithering

def compress_mode9(image: PIL.Image.Image):
    """
    Compress an image using mode 9 compression with optimized color handling.
    Uses numpy for vectorized operations where possible.
    """
    # Convert to RGB and get numpy array
    image = image.convert("RGB")
    width, height = image.size
    data = np.array(image, dtype=np.float32)
    
    # Apply dithering and get processed data and indices
    processed_data, indices = apply_dithering(data, find_closest_color)
    
    # Process image in rows for compression
    rows = [row for row in processed_data]
    buffer = bytearray()
    
    # Compress rows
    for index, row in enumerate(rows):
        if index == 0:
            buffer.extend(compress_line(row, None, True))
        else:
            buffer.extend(compress_line(row, rows[index - 1], False))
    
    return bytes(buffer)

def compress_line(line: np.ndarray, prev_line: np.ndarray | None, first_line: bool):
    """
    Compress a single line of image data using pattern matching and RLE.
    Uses numpy for efficient pattern matching with robust shape handling.
    """
    buffer = bytearray()
    line = np.asarray(line)
    index = 0
    
    while index < len(line):
        pixel = line[index]
        
        # Initialize pattern matching lengths using numpy operations
        lb_copy_length_a = lb_copy_length_b = lb_copy_length_c = 0
        
        if not first_line and prev_line is not None:
            window_size = min(21, len(line) - index)
            
            def compare_arrays(arr1, arr2):
                """Helper function to safely compare arrays of potentially different shapes"""
                if arr1.shape != arr2.shape:
                    min_len = min(len(arr1), len(arr2))
                    arr1 = arr1[:min_len]
                    arr2 = arr2[:min_len]
                return np.all(arr1 == arr2, axis=1)
            
            if index > 0 and index - 1 + window_size <= len(prev_line):
                # Offset -1
                curr_slice = line[index:index+window_size]
                prev_slice = prev_line[index-1:index-1+window_size]
                match_a = compare_arrays(curr_slice, prev_slice)
                lb_copy_length_a = np.argmin(match_a) if not np.all(match_a) else len(match_a)
            
            if index + window_size <= len(prev_line):
                # Offset 0
                curr_slice = line[index:index+window_size]
                prev_slice = prev_line[index:index+window_size]
                match_b = compare_arrays(curr_slice, prev_slice)
                lb_copy_length_b = np.argmin(match_b) if not np.all(match_b) else len(match_b)
            
            if index + 1 < len(prev_line) and index + 1 + window_size <= len(prev_line):
                # Offset 1
                curr_slice = line[index:index+window_size]
                prev_slice = prev_line[index+1:index+1+window_size]
                match_c = compare_arrays(curr_slice, prev_slice)
                lb_copy_length_c = np.argmin(match_c) if not np.all(match_c) else len(match_c)
        
        # RLE compression
        if index + 1 >= len(line):
            rle_length = 0
        else:
            # Compare each subsequent pixel with the current one
            curr_pixel = line[index]
            remaining = line[index:]
            matches = np.all(remaining == curr_pixel, axis=1)
            rle_length = np.argmin(matches) if not np.all(matches) else len(matches)
        
        # Compare compression methods
        compare_dict = {
            "rle": rle_length * 1.2,
            "lb_-1": lb_copy_length_a,
            "lb_0": lb_copy_length_b * 1.1,
            "lb_1": lb_copy_length_c
        }
        
        best_compression = max(compare_dict, key=compare_dict.get)
        best_compression = best_compression.split('*')[0].strip()
        
        if all(value == 0 for value in compare_dict.values()):
            # No compression possible, write color directly
            color_index = find_closest_color([pixel])[0][0]
            buffer.append(color_index)
        elif best_compression == "rle":
            color_index = find_closest_color([pixel])[0][0]
            buffer.append(color_index)
            
            if rle_length >= 6:
                buffer.append(CONTROL_CODES["RLE_6"])
                buffer.append(rle_length - 6)
            else:
                buffer.append(CONTROL_CODES[f"RLE_{rle_length}"])
            
            index += rle_length
        else:
            length = compare_dict[best_compression]
            offset = {"lb_-1": -1, "lb_0": 0, "lb_1": 1}[best_compression]
            
            if 1 <= length <= 5:
                buffer.append(CONTROL_CODES[f"COPY_{int(length)}_OFFSET_{offset}"])
            else:
                buffer.append(CONTROL_CODES[f"COPY_6_OFFSET_{offset}"])
                buffer.append(int(length) - 6)
            
            index += int(length) - 1
        
        index += 1
    
    return bytes(buffer)
