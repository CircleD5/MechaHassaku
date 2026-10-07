# -*- coding: utf-8 -*-
"""Tests for /help pages and slash command definitions (no Discord connection needed)."""
import unittest

import main


class HelpPagesTest(unittest.TestCase):
    PAGES = ("usage", "commands", "tools", "about")

    def test_pages_fit_discord_limits(self):
        for page in self.PAGES:
            with self.subTest(page=page):
                embed = main.build_help_page(page)
                self.assertLessEqual(len(embed), 6000)
                self.assertLessEqual(len(embed.title), 256)
                self.assertLessEqual(len(embed.fields), 25)
                for field in embed.fields:
                    self.assertTrue(field.value)
                    self.assertLessEqual(len(field.value), 1024)

    def test_no_outdated_content(self):
        for page in self.PAGES:
            text = str(main.build_help_page(page).to_dict()).lower()
            with self.subTest(page=page):
                for outdated in ("patreon", "imageparameters", "stable diffusion", "rickroll", "dqw4w9wgxcq",
                                 "youtube", "wd14", "toriato", "lllyasviel", "comfyanonymous", "a1111-web-ui-installer"):
                    self.assertNotIn(outdated, text)

    def test_usage_page_points_to_auto_share_channel(self):
        text = str(main.build_help_page("usage").to_dict())
        self.assertIn(f"<#{main.AUTO_SHARE_CHANNEL_ID}>", text)
        self.assertIn("/checkparameters", text)


class ToolsPageTest(unittest.TestCase):
    def test_links(self):
        text = str(main.build_help_page("tools").to_dict())
        for url in (main.STABILITY_MATRIX_URL, main.STABILITY_MATRIX_INSTALL_URL, main.FORGE_NEO_URL,
                    main.COMFYUI_URL, main.VLCAPTIONER_URL):
            self.assertIn(url, text)


class HelpViewTest(unittest.IsolatedAsyncioTestCase):
    async def test_buttons(self):
        view = main.HelpView()
        labels = [item.label for item in view.children]
        self.assertEqual(
            sorted(labels),
            sorted(["How to use", "Commands", "Tools", "About citrus models", "Civitai", "SubscribeStar", "SeaArt"])
        )
        urls = {item.label: item.url for item in view.children if item.url}
        self.assertEqual(urls, {"Civitai": main.CIVITAI_URL, "SubscribeStar": main.SUBSCRIBESTAR_URL,
                                "SeaArt": main.SEAART_URL})


class SlashCommandsTest(unittest.TestCase):
    def setUp(self):
        self.commands = {c.name: c for c in main.client.tree.get_commands()}

    def test_command_set(self):
        self.assertEqual(set(self.commands), {"ping", "checkparameters", "anonsend", "help"})

    def test_descriptions_fit_limits(self):
        for name, command in self.commands.items():
            with self.subTest(command=name):
                self.assertLessEqual(len(command.description), 100)
                for param in command.parameters:
                    self.assertTrue(param.description and param.description != "…")
                    self.assertLessEqual(len(param.description), 100)

    def test_checkparameters_all_optional(self):
        params = {p.name: p for p in self.commands["checkparameters"].parameters}
        self.assertEqual(set(params), {"image", "link", "private"})
        self.assertFalse(any(p.required for p in params.values()))


class MessageLinkTest(unittest.TestCase):
    def test_links(self):
        cases = {
            "https://discord.com/channels/1072156418402156624/1120359493142843522/1300000000000000000":
                ("1120359493142843522", "1300000000000000000"),
            "https://canary.discord.com/channels/1/2/3": ("2", "3"),
            "https://discordapp.com/channels/@me/22/33": ("22", "33"),
            "look: https://ptb.discord.com/channels/1/44/55 thanks": ("44", "55"),
        }
        for link, (channel, message) in cases.items():
            with self.subTest(link=link):
                match = main.RE_MESSAGE_LINK.search(link)
                self.assertEqual((match.group(2), match.group(3)), (channel, message))

    def test_not_a_link(self):
        for text in ("hello", "https://discord.com/channels/1/2", "https://example.com/channels/1/2/3x"):
            with self.subTest(text=text):
                match = main.RE_MESSAGE_LINK.search(text)
                self.assertTrue(match is None or not text.startswith("https://discord.com"))


if __name__ == "__main__":
    unittest.main()
