# -*- coding: utf-8 -*-
"""Regression tests on real generated images.

The images are not committed (size and content); put them in tests/ locally.
Each test is skipped when its image is missing.
"""
import io
import json
import os
import unittest

from PIL import Image

from module.metadata import read_image_metadata
from module.parser import parse_generation_parameters, parse_novelai_parameters

HERE = os.path.dirname(__file__)
WEBUI_IMAGE = os.path.join(HERE, "00022-4269492586.png")                        # Forge Neo
NOVELAI_V5_IMAGE = os.path.join(HERE, "da17aaf7-cda8-4223-85c4-caaa99d71a6d.png")  # NovelAI V5, text chunks + alpha


@unittest.skipUnless(os.path.exists(WEBUI_IMAGE), "real WebUI image not present")
class WebUIImageTest(unittest.TestCase):
    def test_parameters(self):
        data, stealth = read_image_metadata(Image.open(WEBUI_IMAGE))
        self.assertIsNone(stealth)
        res = parse_generation_parameters(data["parameters"])
        self.assertEqual((res["Seed"], res["Steps"], res["Sampler"]), ("4269492586", "32", "Euler a"))
        self.assertEqual((res["Size-1"], res["Size-2"]), ("960", "1536"))


@unittest.skipUnless(os.path.exists(NOVELAI_V5_IMAGE), "real NovelAI V5 image not present")
class NovelAIV5ImageTest(unittest.TestCase):
    def setUp(self):
        self.image = Image.open(NOVELAI_V5_IMAGE)
        self.image.load()

    def test_text_chunks(self):
        data, stealth = read_image_metadata(self.image)
        self.assertIsNone(stealth)  # text chunks win over the alpha copy
        res = parse_novelai_parameters(data)
        self.assertEqual((res["Model"], res["Model hash"]), ("NovelAI Diffusion V5", "0ADF9AB7"))
        self.assertEqual((res["Seed"], res["Steps"]), ("3439714993", "23"))

    def test_alpha_only_matches_text_chunks(self):
        # Same pixels without any text chunk: everything must come from the alpha channel
        buf = io.BytesIO()
        Image.frombytes("RGBA", self.image.size, self.image.tobytes()).save(buf, "PNG")
        buf.seek(0)
        data, stealth = read_image_metadata(Image.open(buf))
        self.assertEqual((stealth.channel, stealth.compressed), ("alpha", True))
        self.assertEqual(parse_novelai_parameters(data), parse_novelai_parameters(dict(self.image.info)))
        self.assertEqual(json.loads(data["Comment"]), json.loads(self.image.info["Comment"]))


if __name__ == "__main__":
    unittest.main()
