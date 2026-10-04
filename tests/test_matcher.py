import unittest
from src.matcher import Track, is_match, clean_title, clean_artist


class TestMatcher(unittest.TestCase):
    def test_clean_title(self):
        self.assertEqual(clean_title("Blinding Lights (Official Video)"), "Blinding Lights")
        self.assertEqual(clean_title("Song Name [Official Audio]"), "Song Name")
        self.assertEqual(clean_title("Song Name (Lyric Video)"), "Song Name")
        self.assertEqual(clean_title("Song Name (2011 Remaster)"), "Song Name")
        self.assertEqual(clean_title("Song Name - Remastered 2020"), "Song Name")

    def test_clean_artist(self):
        self.assertEqual(clean_artist("The Weeknd"), "weeknd")
        self.assertEqual(clean_artist("Daft Punk"), "daft punk")

    def test_exact_and_fuzzy_matches(self):
        # Case 1: Video tag difference
        t1 = Track(title="Blinding Lights", artists=["The Weeknd"], duration_seconds=200)
        t2 = Track(title="Blinding Lights (Official Music Video)", artists=["The Weeknd"], duration_seconds=202)
        matched, score = is_match(t1, t2)
        self.assertTrue(matched)
        self.assertGreater(score, 90.0)

        # Case 2: Featured artist in title vs artist array
        t3 = Track(title="Get Lucky", artists=["Daft Punk", "Pharrell Williams"], duration_seconds=248)
        t4 = Track(title="Get Lucky (feat. Pharrell Williams)", artists=["Daft Punk"], duration_seconds=250)
        matched, score = is_match(t3, t4)
        self.assertTrue(matched)
        self.assertGreater(score, 80.0)

    def test_different_tracks_do_not_match(self):
        t1 = Track(title="Blinding Lights", artists=["The Weeknd"], duration_seconds=200)
        t2 = Track(title="Save Your Tears", artists=["The Weeknd"], duration_seconds=215)
        matched, score = is_match(t1, t2)
        self.assertFalse(matched)
        self.assertLess(score, 60.0)


if __name__ == "__main__":
    unittest.main()
