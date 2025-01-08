"""
Experimental Scanline image compressor.
Based on the implementation by Palm, Inc.
Optimized using numpy for better performance.
"""
import numpy as np
from typing import Optional
from lib.logger import scanline_logger


def compress_scanline(
    line: bytes,
    prev_line: Optional[bytes] = None,
    first_line: bool = False,
) -> bytes:
    """
    Compress a single line of a bitmap using Scanline compression with numpy optimization.
    
    :param line: The data for the current line
    :param prev_line: The data for the previous line
    :param first_line: True if this is the first line of the image
    """
    # Convert input to numpy arrays for vectorized operations
    line_arr = np.frombuffer(line, dtype=np.uint8)
    if not first_line:
        if prev_line is None or len(prev_line) < len(line):
            raise ValueError("Mismatched lines passed to compress_scanline")
        prev_arr = np.frombuffer(prev_line, dtype=np.uint8)
    
    buffer = bytearray()
    
    if first_line:
        # Process first line in chunks of 8 bytes
        scanline_logger.debug(f"Processing first line: {len(line_arr)} bytes")
        for i in range(0, len(line_arr) - 8, 8):
            buffer.append(0xFF)  # all bytes change on first row
            buffer.extend(line_arr[i:i+8].tobytes())
        
        # Handle remaining bytes
        remaining = len(line_arr) % 8
        if remaining > 0:
            scanline_logger.debug(f"Handling {remaining} remaining bytes in first line")
            buffer.append(0xFF << (8 - remaining) & 0xFF)
            buffer.extend(line_arr[-remaining:].tobytes())
    
    else:
        # Process subsequent lines in chunks of 8 bytes
        for i in range(0, len(line_arr) - 8, 8):
            # Compare 8 bytes at once
            chunk_line = line_arr[i:i+8]
            chunk_prev = prev_arr[i:i+8]
            
            # Find changed bytes using vectorized comparison
            changes = chunk_line != chunk_prev
            flags = np.packbits(changes)[0]
            changed_count = np.count_nonzero(changes)
            
            # Add changed bytes to buffer
            buffer.append(flags)
            buffer.extend(chunk_line[changes].tobytes())
            
            if changed_count > 4:  # Log if more than half the bytes changed
                scanline_logger.debug(f"High change detected: {changed_count}/8 bytes at offset {i}")
        
        # Handle remaining bytes
        remaining = len(line_arr) % 8
        if remaining > 0:
            chunk_line = line_arr[-remaining:]
            chunk_prev = prev_arr[-remaining:]
            
            changes = chunk_line != chunk_prev
            flags = np.packbits(np.pad(changes, (0, 8-remaining), 'constant'))[0]
            changed_count = np.count_nonzero(changes)
            
            buffer.append(flags)
            buffer.extend(chunk_line[changes].tobytes())
            
            if changed_count > remaining/2:  # Log if more than half the remaining bytes changed
                scanline_logger.debug(f"High change detected in remaining bytes: {changed_count}/{remaining}")
    
    compressed_size = len(buffer)
    ratio = compressed_size / len(line) * 100
    scanline_logger.debug(f"Line compression: {len(line)} -> {compressed_size} bytes ({ratio:.1f}%)")
    return bytes(buffer)


def compress_data_with_scanline(data: bytes, width: int) -> bytes:
    """
    Compress a block of data with Scanline using numpy optimization.
    
    :param data: Image data
    :param width: Width of one row of the image, in bytes
    """
    scanline_logger.debug(f"Starting scanline compression: data size={len(data)} bytes, row width={width} bytes")
    
    # Convert input to numpy array and reshape into rows
    data_arr = np.frombuffer(data, dtype=np.uint8)
    rows = data_arr.reshape(-1, width)
    num_rows = len(rows)
    scanline_logger.debug(f"Image dimensions: {num_rows} rows x {width} bytes per row")
    
    buffer = bytearray()
    
    # Process first row
    scanline_logger.debug("Compressing first row")
    first_row_compressed = compress_scanline(rows[0].tobytes(), None, True)
    buffer.extend(first_row_compressed)
    
    # Process subsequent rows
    for i in range(1, num_rows):
        row_compressed = compress_scanline(rows[i].tobytes(), rows[i-1].tobytes(), False)
        buffer.extend(row_compressed)
        if i % 10 == 0:  # Log progress every 10 rows
            scanline_logger.debug(f"Compressed {i}/{num_rows} rows")
    
    compressed_size = len(buffer)
    ratio = compressed_size / len(data) * 100
    scanline_logger.debug(f"Scanline compression complete: {len(data)} -> {compressed_size} bytes ({ratio:.1f}%)")
    return bytes(buffer)
