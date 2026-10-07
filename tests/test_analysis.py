# -*- coding: utf-8 -*-
"""Tests for embed building, tags, model answers and the in-memory analysis flow."""
import io
import json
import os
import unittest

from PIL import Image, PngImagePlugin

import main
from tests.test_stealth import NAI_V5_STEALTH, embed as embed_stealth, noise_image

WEBUI_TEXT = ("masterpiece, 1girl\n"
              "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 42, Size: 512x768, Model hash: abc123, Model: hassakuXL")


def png_bytes(image: Image.Image, text: dict = None) -> bytes:
    info = PngImagePlugin.PngInfo()
    for k, v in (text or {}).items():
        info.add_text(k, v)
    buf = io.BytesIO()
    image.save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


class FakeAttachment:
    def __init__(self, data: bytes, filename="image.png", content_type="image/png"):
        self._data, self.filename, self.content_type = data, filename, content_type

    async def read(self):
        return self._data


class Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def field_names(embed):
    return [f.name for f in embed.fields]


class EmbedTest(unittest.TestCase):
    def test_empty_negative_prompt_is_not_a_field(self):
        ed = main._parse_parameters({"parameters": WEBUI_TEXT})
        self.assertEqual(ed["Negative prompt"], "")
        embed = main.create_pnginfo_view(ed)
        self.assertFalse(any("Negative" in n for n in field_names(embed)))
        self.assertTrue(all(f.value.strip() for f in embed.fields))

    def test_huge_prompt_is_cut_to_fit(self):
        ed = main._parse_parameters({"parameters": ("tag, " * 4000) + "\nNegative prompt: " + ("bad, " * 3000)
                                                   + "\n" + WEBUI_TEXT.split("\n")[1]})
        embed = main.create_pnginfo_view(ed)
        self.assertLessEqual(len(embed), main.EMBED_TOTAL_LIMIT)
        self.assertLessEqual(len(embed.fields), main.EMBED_MAX_FIELDS)
        self.assertIn("full text in fullParameters.txt", str(embed.to_dict()))
        self.assertIn("__Seed__ :game_die:", field_names(embed))

    def test_short_prompt_is_not_cut(self):
        embed = main.create_pnginfo_view(main._parse_parameters({"parameters": WEBUI_TEXT}))
        self.assertNotIn("cut —", str(embed.to_dict()))

    def test_comfyui_has_description_only(self):
        embed = main.create_pnginfo_view(main._parse_parameters({"prompt": "{}"}))
        self.assertEqual(len(embed.fields), 0)
        self.assertIn("ComfyUI", embed.description)


class TagTest(unittest.TestCase):
    def tags(self, **kv):
        return main._detect_tags(kv)

    def test_anima_by_text_encoder_module(self):
        # As written by Forge Neo for an Anima-based model
        self.assertIn("ANIMA", self.tags(Prompt="1girl", Model="IkaViVid.fp16",
                                         **{"Module 1": "qwen_image_vae", "Module 2": "qwen_3_06b_base"}))

    def test_anima_by_model_name(self):
        for name in ("anima-preview2", "AnimaYume_v1", "anima_base_v1.0"):
            with self.subTest(name=name):
                self.assertIn("ANIMA", self.tags(Prompt="x", Model=name))

    def test_not_anima(self):
        for name, expected in (("animagineXL40", "SDXL"), ("waiNSFWIllustrious", "ILLUSTRIOUS"),
                               ("animatediffModel", None), ("hassakuXL", "SDXL")):
            with self.subTest(name=name):
                tags = self.tags(Prompt="x", Model=name)
                self.assertNotIn("ANIMA", tags)
                if expected:
                    self.assertIn(expected, tags)


class ModelAnswerTest(unittest.TestCase):
    def test_webui(self):
        answer = main.model_answer(main._parse_parameters({"parameters": WEBUI_TEXT}))
        self.assertIn("`hassakuXL`", answer)
        self.assertIn("`abc123`", answer)

    def test_novelai(self):
        answer = main.model_answer(main._parse_parameters(dict(NAI_V5_STEALTH)))
        self.assertIn("`NovelAI Diffusion V5`", answer)
        self.assertIn("`0ADF9AB7`", answer)

    def test_comfyui_and_unknown(self):
        self.assertIsNone(main.model_answer(main._parse_parameters({"prompt": "{}"})))
        self.assertIsNone(main.model_answer({"ui_type": "webui", "Prompt": "x"}))


class AnalysisFlowTest(unittest.IsolatedAsyncioTestCase):
    async def analyze(self, data: bytes):
        before = set(os.listdir("."))
        send = Recorder()
        await main.analyze_attachment_and_reply(FakeAttachment(data), send)
        self.assertEqual(set(os.listdir(".")), before, "analysis must not write files")
        return send.calls

    async def test_webui_image(self):
        calls = await self.analyze(png_bytes(Image.new("RGB", (1536, 1024)), {"parameters": WEBUI_TEXT}))
        (_, first), (_, second) = calls
        self.assertEqual(first["file"].filename, main.THUMBNAIL_NAME)
        self.assertEqual(first["embed"].thumbnail.url, f"attachment://{main.THUMBNAIL_NAME}")
        with Image.open(first["file"].fp) as thumb:
            self.assertLessEqual(max(thumb.size), 512)
        self.assertEqual(second["file"].filename, "fullParameters.txt")
        self.assertIn(b"masterpiece", second["file"].fp.read())

    async def test_novelai_stealth_image(self):
        image = embed_stealth(noise_image(), json.dumps(NAI_V5_STEALTH), "alpha", True)
        calls = await self.analyze(png_bytes(image))
        title = calls[0][1]["embed"].title
        self.assertIn("NOVEL AI", title)
        self.assertIn("STEALTH", title)

    async def test_no_parameters(self):
        calls = await self.analyze(png_bytes(Image.new("RGB", (64, 64))))
        self.assertIn("No parameters detected", calls[0][0][0])


if __name__ == "__main__":
    unittest.main()
