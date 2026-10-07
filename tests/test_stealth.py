# -*- coding: utf-8 -*-
"""Tests for stealth pnginfo reading and NovelAI parsing. Run: python -m unittest discover tests"""
import gzip
import io
import json
import random
import unittest

from PIL import Image, PngImagePlugin, features

from module.metadata import read_image_metadata
from module.parser import parse_generation_parameters, parse_novelai_parameters
from module.stealth import find_stealth, stealth_to_info


# ==================== Writer (mirrors the A1111 extension / NovelAI writers) ====================
def embed(image: Image.Image, text: str, channel: str = "alpha", compressed: bool = True,
          nai_fec_marker: bool = False) -> Image.Image:
    magic = f"stealth_{'png' if channel == 'alpha' else 'rgb'}{'comp' if compressed else 'info'}"
    payload = gzip.compress(text.encode("utf-8")) if compressed else text.encode("utf-8")
    data = magic.encode() + (len(payload) * 8).to_bytes(4, "big") + payload
    if nai_fec_marker:
        data += (0xFFFFFFFF).to_bytes(4, "big")
    bits = "".join(f"{b:08b}" for b in data)

    image = image.convert("RGBA" if channel == "alpha" else "RGB")
    pixels = image.load()
    width, height = image.size
    index = 0
    for x in range(width):
        for y in range(height):
            if index >= len(bits):
                return image
            p = list(pixels[x, y])
            if channel == "alpha":
                p[3] = (p[3] & ~1) | int(bits[index])
                index += 1
            else:
                for c in range(3):
                    if index < len(bits):
                        p[c] = (p[c] & ~1) | int(bits[index])
                        index += 1
            pixels[x, y] = tuple(p)
    raise ValueError("image too small for payload")


def noise_image(width=64, height=96, mode="RGBA", seed=0) -> Image.Image:
    rnd = random.Random(seed)
    return Image.frombytes(mode, (width, height), bytes(rnd.randrange(256) for _ in range(width * height * len(mode))))


def roundtrip(image: Image.Image, fmt="PNG", **kwargs) -> Image.Image:
    buf = io.BytesIO()
    image.save(buf, fmt, **kwargs)
    buf.seek(0)
    return Image.open(buf)


NAI_V5_COMMENT = {
    "prompt": "1girl, solo, orange hair",
    "uc": "lowres, bad anatomy",
    "steps": 28, "scale": 5.5, "seed": 123456789, "sampler": "k_euler_ancestral",
    "noise_schedule": "karras", "width": 832, "height": 1216,
    "v4_prompt": {"caption": {"base_caption": "1girl, solo, orange hair",
                              "char_captions": [{"char_caption": "girl, smile", "centers": [{"x": 0.5, "y": 0.5}]},
                                                {"char_caption": "", "centers": []}]},
                  "use_coords": False, "use_order": True},
    "v4_negative_prompt": {"caption": {"base_caption": "lowres, bad anatomy",
                                       "char_captions": [{"char_caption": "frown", "centers": []}]}},
    "request_type": "PromptGenerateRequest",
}
NAI_V5_STEALTH = {
    "Description": "1girl, solo, orange hair",
    "Software": "NovelAI",
    "Source": "NovelAI Diffusion V5 0ADF9AB7",
    "Generation time": "3.1",
    "Comment": json.dumps(NAI_V5_COMMENT),
}
A1111_TEXT = ("masterpiece, 1girl\nNegative prompt: lowres\n"
              "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 42, Size: 512x768, Model hash: abc123, Model: hassakuXL")


class StealthReaderTest(unittest.TestCase):
    def test_alpha_compressed_novelai(self):
        image = embed(noise_image(), json.dumps(NAI_V5_STEALTH), "alpha", True, nai_fec_marker=True)
        found = find_stealth(roundtrip(image))
        self.assertEqual((found.channel, found.compressed), ("alpha", True))
        self.assertEqual(json.loads(found.text), NAI_V5_STEALTH)

    def test_all_four_signatures(self):
        for channel in ("alpha", "rgb"):
            for compressed in (False, True):
                with self.subTest(channel=channel, compressed=compressed):
                    mode = "RGBA" if channel == "alpha" else "RGB"
                    image = embed(noise_image(mode=mode), A1111_TEXT, channel, compressed)
                    found = find_stealth(roundtrip(image))
                    self.assertEqual((found.channel, found.compressed, found.text),
                                     (channel, compressed, A1111_TEXT))

    def test_rgb_in_rgba_image(self):
        image = noise_image(mode="RGBA")
        rgb = embed(image, A1111_TEXT, "rgb", True)
        rgb.putalpha(image.getchannel("A"))
        self.assertEqual(find_stealth(roundtrip(rgb)).channel, "rgb")

    def test_payload_spanning_many_columns(self):
        # Height 7 forces the payload across many columns; checks the column-major order
        text = "x" * 500
        image = embed(noise_image(width=900, height=7), text, "alpha", False)
        self.assertEqual(find_stealth(image).text, text)

    def test_multibyte_text(self):
        text = "少女、オレンジ色の髪\nSteps: 20, Sampler: Euler a, CFG scale: 7"
        self.assertEqual(find_stealth(embed(noise_image(), text, "alpha", False)).text, text)

    def test_no_stealth(self):
        self.assertIsNone(find_stealth(noise_image(mode="RGBA")))
        self.assertIsNone(find_stealth(noise_image(mode="RGB")))
        self.assertIsNone(find_stealth(Image.new("RGBA", (64, 64), (255, 255, 255, 255))))
        self.assertIsNone(find_stealth(Image.new("L", (64, 64))))

    def test_too_small_image(self):
        self.assertIsNone(find_stealth(noise_image(width=5, height=5)))

    def test_length_beyond_capacity(self):
        image = embed(noise_image(), "abc", "alpha", False)
        # Set the highest bit of the 32-bit length field (first bit after the 120-bit magic)
        a = image.getchannel("A")
        x, y = divmod(120, image.height)
        a.putpixel((x, y), a.getpixel((x, y)) | 1)
        image.putalpha(a)
        self.assertIsNone(find_stealth(image))

    def test_corrupted_gzip(self):
        image = embed(noise_image(), A1111_TEXT, "alpha", True)
        # Flip the LSBs of a few pixels inside the deflate stream (bytes 0-9 are the gzip header,
        # whose mtime field is not verified on decompression)
        a = image.getchannel("A")
        for i in range(HEADER_PIXELS + 200, HEADER_PIXELS + 240):
            x, y = divmod(i, image.height)
            a.putpixel((x, y), a.getpixel((x, y)) ^ 1)
        image.putalpha(a)
        self.assertIsNone(find_stealth(image))

    def test_rgb_payload_in_opaque_rgba(self):
        # RGB-mode data saved as RGBA with a plain opaque alpha: alpha has no magic, RGB does
        image = embed(noise_image(mode="RGB"), A1111_TEXT, "rgb", False)
        self.assertEqual(find_stealth(roundtrip(image.convert("RGBA"))).text, A1111_TEXT)

    @unittest.skipUnless(features.check("webp"), "Pillow built without WebP")
    def test_lossless_webp(self):
        image = embed(noise_image(), json.dumps(NAI_V5_STEALTH), "alpha", True, nai_fec_marker=True)
        found = find_stealth(roundtrip(image, "WEBP", lossless=True, exact=True))
        self.assertEqual(json.loads(found.text), NAI_V5_STEALTH)

    def test_jpeg_is_not_misdetected(self):
        image = embed(noise_image(mode="RGB"), A1111_TEXT, "rgb", False)
        self.assertIsNone(find_stealth(roundtrip(image, "JPEG", quality=90)))


HEADER_PIXELS = 152  # 120-bit magic + 32-bit length, one bit per pixel in alpha mode


class MetadataTest(unittest.TestCase):
    def test_text_chunks_take_priority(self):
        image = embed(noise_image(), json.dumps(NAI_V5_STEALTH), "alpha", True)
        info = PngImagePlugin.PngInfo()
        info.add_text("parameters", A1111_TEXT)
        data, stealth = read_image_metadata(roundtrip(image, pnginfo=info))
        self.assertIsNone(stealth)
        self.assertEqual(data["parameters"], A1111_TEXT)
        self.assertNotIn("Comment", data)

    def test_stealth_used_when_no_text_chunks(self):
        image = embed(noise_image(), json.dumps(NAI_V5_STEALTH), "alpha", True)
        data, stealth = read_image_metadata(roundtrip(image))
        self.assertEqual(stealth.channel, "alpha")
        self.assertEqual(data["Source"], "NovelAI Diffusion V5 0ADF9AB7")

    def test_stealth_a1111_text_becomes_parameters(self):
        image = embed(noise_image(), A1111_TEXT, "alpha", True)
        data, _ = read_image_metadata(roundtrip(image))
        self.assertEqual(parse_generation_parameters(data["parameters"])["Steps"], "20")

    def test_inner_comment_only(self):
        self.assertEqual(stealth_to_info(json.dumps(NAI_V5_COMMENT)), {"Comment": NAI_V5_COMMENT})

    def test_text_chunk_after_image_data_is_found(self):
        # Same case that made the old code save the image to disk before reading info
        buf = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buf, "PNG")
        png = buf.getvalue()
        import struct
        import zlib
        chunk_data = b"parameters\x00" + A1111_TEXT.encode("latin-1")
        chunk = (struct.pack(">I", len(chunk_data)) + b"tEXt" + chunk_data
                 + struct.pack(">I", zlib.crc32(b"tEXt" + chunk_data) & 0xFFFFFFFF))
        iend = png.rfind(b"IEND") - 4
        data, stealth = read_image_metadata(Image.open(io.BytesIO(png[:iend] + chunk + png[iend:])))
        self.assertEqual(data["parameters"], A1111_TEXT)
        self.assertIsNone(stealth)


class NovelAIParserTest(unittest.TestCase):
    def test_v5_from_stealth(self):
        res = parse_novelai_parameters(stealth_to_info(json.dumps(NAI_V5_STEALTH)))
        self.assertEqual(res["Prompt"], "1girl, solo, orange hair\n\nCharacter 1: girl, smile")
        self.assertEqual(res["Negative prompt"], "lowres, bad anatomy\n\nCharacter 1: frown")
        self.assertEqual(res["Model"], "NovelAI Diffusion V5")
        self.assertEqual(res["Model hash"], "0ADF9AB7")
        self.assertEqual((res["Seed"], res["Steps"], res["CFG scale"]), ("123456789", "28", "5.5"))
        self.assertEqual((res["Size-1"], res["Size-2"]), ("832", "1216"))
        self.assertEqual(res["Schedule type"], "karras")

    def test_v3_legacy(self):
        comment = {"prompt": "1girl", "uc": "lowres", "steps": 28, "scale": 5, "seed": 1,
                   "sampler": "k_euler", "width": 832, "height": 1216}
        res = parse_novelai_parameters({"Source": "Stable Diffusion XL C1E1DE52", "Comment": json.dumps(comment)})
        self.assertEqual((res["Prompt"], res["Negative prompt"]), ("1girl", "lowres"))
        self.assertEqual((res["Model"], res["Model hash"]), ("Stable Diffusion XL", "C1E1DE52"))

    def test_internal_model_name_mapped_by_hash(self):
        res = parse_novelai_parameters({"Source": "DiffusionModelMetaName.NAIv4next 4BDE2A90",
                                        "Comment": json.dumps({"prompt": "a"})})
        self.assertEqual(res["Model"], "NovelAI Diffusion V4.5")

    def test_no_empty_values(self):
        res = parse_novelai_parameters({"Comment": json.dumps({"prompt": "a", "uc": ""})})
        self.assertEqual(res, {"Prompt": "a"})


if __name__ == "__main__":
    unittest.main()
