"""Classes for converting from PIL image to Xiino-format bytes."""
import math
import os
from base64 import b64encode
from dataclasses import dataclass
import PIL.Image
import PIL.ImageOps
import bitstring
import cairosvg
import io
import asyncio
from typing import Union, Optional, List, Tuple, Dict, Any
import numpy as np

# Security constants
MAX_SVG_SIZE = 1024 * 1024  # 1MB max SVG size
SVG_PROCESSING_TIMEOUT = 5  # 5 second timeout for SVG processing

import lib.scanline as scanline
import lib.mode9 as mode9
from lib.xiino_palette_common import PALETTE
from lib.logger import image_logger
from lib.dithering import apply_dithering
from lib.color_matching import (
    find_closest_color,
    find_closest_gray,
    GRAY_PALETTE_2BIT,
    GRAY_PALETTE_4BIT,
    PALETTE_ARRAY
)

@dataclass
class EBDImage:
    """An image that has been converted to an EBDIMAGE format."""
    raw_data: bytes
    width: int
    height: int
    mode: int

    def generate_ebdimage_tag(self, name: str) -> str:
        """Generate an EBDIMAGE tag for the data of this image."""
        base64 = b64encode(self.raw_data).decode("latin-1")
        return (
            f"""<EBDIMAGE MODE="{self.mode}" NAME="{name}"><!--{base64}--></EBDIMAGE>"""
        )

    def generate_img_tag(self, name: str, alt_text: Optional[str] = None) -> str:
        """Generate an IMG tag for this image."""
        return f"""<IMG ALT="{alt_text or ''}" WIDTH="{self.width}" HEIGHT="{self.height}" EBDWIDTH="{self.width}" EBDHEIGHT="{self.height}" EBD="{name}">"""

class EBDConverter:
    """Convert from a PIL image to any of the modes known to be supported by Xiino."""

    def __init__(
        self,
        image: Union[PIL.Image.Image, str]
    ) -> None:
        """Initialize with safety checks and limits."""
        self._image = image
        self.image: Optional[PIL.Image.Image] = None
        self._cleanup_required = False

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self._cleanup_required and self.image:
            await asyncio.to_thread(self.image.close)
            self.image = None
            self._cleanup_required = False

    def __extract_svg_dimensions(self, svg_content: str) -> Tuple[int, int]:
        """Extract width and height from SVG content."""
        import re
        
        # Try to extract from width/height attributes with units
        width_match = re.search(r'width="(\d+(?:\.\d+)?)\s*(?:px|pt|mm|cm|in|%)?', svg_content)
        height_match = re.search(r'height="(\d+(?:\.\d+)?)\s*(?:px|pt|mm|cm|in|%)?', svg_content)
        
        if width_match and height_match:
            width = float(width_match.group(1))
            height = float(height_match.group(1))
            # If dimensions are percentages, try to get actual size from viewBox
            if '%' in width_match.group(0) or '%' in height_match.group(0):
                viewbox_match = re.search(r'viewBox="[^"]*?\s+[^"]*?\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"', svg_content)
                if viewbox_match:
                    return int(float(viewbox_match.group(1))), int(float(viewbox_match.group(2)))
            return int(width), int(height)
            
        # Try to extract from viewBox
        viewbox_match = re.search(r'viewBox="[^"]*?\s+[^"]*?\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"', svg_content)
        if viewbox_match:
            return int(float(viewbox_match.group(1))), int(float(viewbox_match.group(2)))
            
        # Default to device width if no dimensions found
        return 306, 306

    async def _convert_svg(self, svg_content: str, is_file: bool = False) -> PIL.Image.Image:
        """Convert SVG to PNG with security checks and proper scaling."""
        if len(svg_content.encode('utf-8')) > MAX_SVG_SIZE:
            raise ValueError("SVG content exceeds maximum allowed size")
            
        try:
            # Extract original dimensions
            orig_width, orig_height = self.__extract_svg_dimensions(svg_content)
            
            # Direct synchronous conversion at original size
            png_data = cairosvg.svg2png(
                url=svg_content if is_file else None,
                bytestring=svg_content.encode('utf-8') if not is_file else None,
                output_width=orig_width,
                output_height=orig_height,
                scale=1.0
            )
            return PIL.Image.open(io.BytesIO(png_data))
                    
        except asyncio.TimeoutError:
            raise TimeoutError("SVG processing timeout")
        except Exception as e:
            raise ValueError(f"Invalid SVG content: {str(e)}")

    async def _initialize(self) -> None:
        """Initialize the converter asynchronously."""
        try:
            if isinstance(self._image, str):
                # Process SVG with security checks
                if self._image.lower().endswith('.svg') or '<svg' in self._image[:1000].lower():
                    # Check SVG size before processing
                    svg_content = self._image
                    if not self._image.lower().endswith('.svg'):
                        svg_size = len(svg_content.encode('utf-8'))
                        if svg_size > MAX_SVG_SIZE:
                            raise ValueError("SVG content exceeds maximum allowed size")
                    else:
                        # For file paths, check file size
                        if os.path.getsize(self._image) > MAX_SVG_SIZE:
                            raise ValueError("SVG content exceeds maximum allowed size")
                        
                    image = await self._convert_svg(
                        self._image, 
                        is_file=self._image.lower().endswith('.svg')
                    )
                else:
                    # Open regular image file with size validation
                    image = PIL.Image.open(self._image)
                    if image.width * image.height > 1000000:
                        raise ValueError("Image dimensions too large")
            else:
                image = self._image

            # Check image dimensions before any scaling
            if image.width * image.height > 1000000:
                raise ValueError("Image dimensions too large")

            # Apply Xiino's scaling requirements
            if image.width > 306:
                # Scale down to 153 pixels for large images
                new_width = 153
                new_height = int((image.height / image.width) * 153)
                image = image.resize(
                    (new_width, new_height),
                    PIL.Image.Resampling.LANCZOS
                )
            elif image.width > 100:
                # Scale to half size for medium images
                new_width = int(image.width * 0.5)
                new_height = int(image.height * 0.5)
                image = image.resize(
                    (new_width, new_height),
                    PIL.Image.Resampling.LANCZOS
                )
            # Images <= 100px wide are not scaled

            # Handle transparency
            try:
                # Convert palette images with transparency to RGBA first
                if image.mode == "P" and image.info.get("transparency") is not None:
                    image = image.convert("RGBA")
                
                if image.mode == "RGBA":
                    background = PIL.Image.new("RGBA", image.size, (255, 255, 255))
                    self.image = PIL.Image.alpha_composite(background, image).convert("RGB")
                else:
                    self.image = image.convert("RGB")
            except ValueError as e:
                image_logger.error(f"Image composite failed for size {image.size}")
                raise e
                
            self._cleanup_required = True
        except Exception as e:
            image_logger.error(f"Initialization failed: {str(e)}")
            raise

    async def convert_bw(self, compressed: bool = False) -> EBDImage:
        """Convert the image to black and white (1-bit)."""
        if not self.image:
            await self._initialize()
        if compressed:
            data = self._convert_mode1()
            return EBDImage(data, width=self.image.width, height=self.image.height, mode=1)
        data = self._convert_mode0()
        return EBDImage(data, width=self.image.width, height=self.image.height, mode=0)

    async def convert_gs(self, depth: int = 4, compressed: bool = False) -> EBDImage:
        """Convert the image to greyscale."""
        if not self.image:
            await self._initialize()
        if depth == 2:
            if compressed:
                data = self._convert_mode3()
                return EBDImage(data, width=self.image.width, height=self.image.height, mode=3)
            data = self._convert_mode2()
            return EBDImage(data, width=self.image.width, height=self.image.height, mode=2)
        elif depth == 4:
            if compressed:
                data = self._convert_mode4()
                return EBDImage(data, width=self.image.width, height=self.image.height, mode=4)
            data = self._convert_mode5()
            return EBDImage(data, width=self.image.width, height=self.image.height, mode=5)
        else:
            raise ValueError("Unsupported bit depth for greyscale.")

    async def convert_colour(self, compressed: bool = False) -> EBDImage:
        """Convert the image to 8-bit (231 colour)."""
        if not self.image:
            await self._initialize()
        if compressed:
            data = mode9.compress_mode9(self.image)
            return EBDImage(data, width=self.image.width, height=self.image.height, mode=9)
        data = self._convert_mode8()
        return EBDImage(data, width=self.image.width, height=self.image.height, mode=8)

    def _convert_mode0(self) -> bytes:
        """Convert to mode0 (one-bit, no compression) using numpy."""
        # Convert to binary image and get numpy array
        im_bw = np.array(self.image.convert("1"), dtype=np.bool_)
        
        # Pad width to multiple of 8 for byte alignment
        pad_width = (8 - (im_bw.shape[1] % 8)) % 8
        if pad_width:
            im_bw = np.pad(im_bw, ((0, 0), (0, pad_width)), mode='constant', constant_values=0)
        
        # Reshape to group bits into bytes (8 pixels per byte)
        bits = np.packbits(~im_bw, axis=1)
        
        return bytes(bits.flatten())

    def _convert_mode1(self) -> bytes:
        """Convert to mode1 (one-bit, scanline compression)."""
        width_bytes = math.ceil(self.image.width / 8)  # 8 pixels per byte for black and white
        return scanline.compress_data_with_scanline(self._convert_mode0(), width_bytes)

    def _convert_mode2(self) -> bytes:
        """Convert to uncompressed two-bit grey using numpy."""
        # Convert to grayscale and invert
        im_gs = np.array(PIL.ImageOps.invert(self.image.convert("L")), dtype=np.uint8)
        
        # Apply dithering with 4 levels (2 bits)
        _, quantized = apply_dithering(
            im_gs,
            lambda x: find_closest_gray(x, 4),
            palette_array=GRAY_PALETTE_2BIT
        )
        
        # Pad width to multiple of 4 for byte alignment
        pad_width = (4 - (quantized.shape[1] % 4)) % 4
        if pad_width:
            quantized = np.pad(quantized, ((0, 0), (0, pad_width)), mode='constant')
        
        # Pack 4 2-bit values into each byte
        packed = np.zeros(quantized.shape[0] * ((quantized.shape[1] + 3) // 4), dtype=np.uint8)
        for i in range(4):
            shift = 6 - (i * 2)
            mask = (quantized[:, i::4].flatten()[:len(packed)] << shift)
            packed |= mask
            
        return bytes(packed)

    def _convert_mode3(self) -> bytes:
        """Convert to Scanline compressed two-bit grey."""
        width_bytes = math.ceil(self.image.width / 2)
        return scanline.compress_data_with_scanline(self._convert_mode2(), width_bytes)

    def _convert_mode4(self) -> bytes:
        """Convert to uncompressed four-bit grey using numpy."""
        # Convert to grayscale and invert
        im_gs = np.array(PIL.ImageOps.invert(self.image.convert("L")), dtype=np.uint8)
        
        # Apply dithering with 16 levels (4 bits)
        _, quantized = apply_dithering(
            im_gs,
            lambda x: find_closest_gray(x, 16),
            palette_array=GRAY_PALETTE_4BIT
        )
        
        # Pad width to multiple of 2 for byte alignment
        if quantized.shape[1] % 2:
            quantized = np.pad(quantized, ((0, 0), (0, 1)), mode='constant')
        
        # Pack pairs of 4-bit values into bytes
        high = quantized[:, ::2] << 4
        low = quantized[:, 1::2]
        packed = high | low
        
        return bytes(packed.flatten())

    def _convert_mode5(self) -> bytes:
        """Convert to Scanline compressed four-bit grey."""
        width_bytes = math.ceil(self.image.width / 4)
        return scanline.compress_data_with_scanline(self._convert_mode4(), width_bytes)

    def _convert_mode8(self) -> bytes:
        """Convert to 8-bit color using vectorized numpy operations."""
        # Get image data as numpy array
        pixels = np.array(self.image, dtype=np.float32)
        
        # Apply dithering and get indices
        _, indices = apply_dithering(pixels, find_closest_color, palette_array=PALETTE_ARRAY)
        
        return bytes(indices.flatten())

    @staticmethod
    def _divide_chunks(l: List[Any], n: int) -> List[Any]:
        """Helper function for splitting things into chunks."""
        return [l[i:i + n] for i in range(0, len(l), n)]
