import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "yuntu_highlights.py"


def load_module():
    spec = importlib.util.spec_from_file_location("yuntu_highlights", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detail_with_trends(*trends, high_points=None):
    return {
        "trend_series": list(trends),
        "high_points": high_points or [],
    }


class YuntuHighlightTests(unittest.TestCase):
    def test_configured_candidates_support_local_peaks_and_top_values(self):
        highlights = load_module()
        detail = detail_with_trends(
            {
                "trend_name": "点击指数",
                "series": [
                    {"second": 0, "value": 0}, {"second": 1, "value": 9},
                    {"second": 2, "value": 1}, {"second": 3, "value": 8},
                ],
            },
            {
                "trend_name": "点赞指数",
                "series": [
                    {"second": 0, "value": 2}, {"second": 1, "value": 12},
                    {"second": 2, "value": 4},
                ],
            },
        )
        candidates = highlights.select_highlight_candidates_by_spec(
            detail,
            {
                "include_cover": True,
                "metrics": {
                    "点击指数": {"strategy": "local_peaks", "limit": 2},
                    "点赞指数": {"strategy": "top_values", "limit": 1},
                },
            },
        )
        self.assertEqual([candidate["second"] for candidate in candidates], [0, 1, 3])
        self.assertEqual(candidates[1]["reasons"][-1]["type"], "top_values")

    def test_configured_candidates_merge_reasons_at_same_second(self):
        highlights = load_module()
        detail = detail_with_trends(
            {"trend_name": "点击指数", "series": [{"second": 4, "value": 1}, {"second": 5, "value": 9}, {"second": 6, "value": 1}]},
            {"trend_name": "点赞指数", "series": [{"second": 4, "value": 2}, {"second": 5, "value": 12}, {"second": 6, "value": 2}]},
        )
        candidates = highlights.select_highlight_candidates_by_spec(
            detail,
            {"include_cover": False, "metrics": {
                "点击指数": {"strategy": "local_peaks", "limit": 1},
                "点赞指数": {"strategy": "top_values", "limit": 1},
            }},
        )
        self.assertEqual([item["second"] for item in candidates], [5])
        self.assertEqual({reason["trend_name"] for reason in candidates[0]["reasons"]}, {"点击指数", "点赞指数"})

    def test_top_values_selects_distinct_seconds_by_value_then_second(self):
        highlights = load_module()
        detail = detail_with_trends(
            {
                "trend_name": "点击指数",
                "series": [
                    {"second": 20, "value": 8},
                    {"second": 10, "value": 9},
                    {"second": 5, "value": 9},
                    {"second": 15, "value": 7},
                ],
            },
        )

        candidates = highlights.select_highlight_candidates_by_spec(
            detail,
            {
                "include_cover": False,
                "metrics": {"点击指数": {"strategy": "top_values", "limit": 2}},
            },
        )

        self.assertEqual([candidate["second"] for candidate in candidates], [5, 10])
        self.assertEqual(
            [candidate["reasons"][0]["rank"] for candidate in candidates], [1, 2]
        )

    def test_configured_highlights_require_matching_nonempty_local_frames(self):
        highlights = load_module()
        detail = {
            "material_id": "101",
            "trend_series": [{
                "trend_name": "点击指数",
                "series": [
                    {"second": 0, "value": 0},
                    {"second": 5, "value": 4},
                    {"second": 6, "value": 0},
                ],
            }],
        }
        spec = {"include_cover": False, "metrics": {
            "点击指数": {"strategy": "local_peaks", "limit": 1},
        }}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "highlights" / "101" / "wrong-second.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"jpeg")
            highlights.write_highlights_manifest(root, {
                "101": [{
                    "available": True,
                    "frame_type": "custom_highlight",
                    "second": 9,
                    "relative_path": "highlights/101/wrong-second.jpg",
                }],
            })
            self.assertEqual(
                highlights.details_missing_highlights_by_spec([detail], root, spec),
                [detail],
            )

            image.unlink()
            image = root / "highlights" / "101" / "expected-second.jpg"
            image.touch()
            highlights.write_highlights_manifest(root, {
                "101": [{
                    "available": True,
                    "frame_type": "custom_highlight",
                    "second": 5,
                    "relative_path": "highlights/101/expected-second.jpg",
                }],
            })
            self.assertEqual(
                highlights.details_missing_highlights_by_spec([detail], root, spec),
                [detail],
            )

    def test_generate_missing_highlights_preserves_available_frames(self):
        highlights = load_module()
        detail = {
            "material_id": "101",
            "video_url": "https://example.test/video.mp4",
            "trend_series": [{
                "trend_name": "点击指数",
                "series": [
                    {"second": 0, "value": 0},
                    {"second": 1, "value": 4},
                    {"second": 2, "value": 0},
                    {"second": 3, "value": 5},
                    {"second": 4, "value": 0},
                ],
            }],
        }
        spec = {"include_cover": False, "metrics": {
            "点击指数": {"strategy": "local_peaks", "limit": 2},
        }}
        requested_seconds = []

        def downloader(_url, destination):
            Path(destination).write_bytes(b"video")

        def batch_extractor(_video, requests, **_kwargs):
            requested_seconds.extend(request["second"] for request in requests)
            for request in requests:
                Path(request["destination"]).write_bytes(b"new-jpeg")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preserved = root / "highlights" / "101" / "01-001s.jpg"
            preserved.parent.mkdir(parents=True)
            preserved.write_bytes(b"preserved-jpeg")
            highlights.write_highlights_manifest(root, {
                "101": [{
                    "available": True,
                    "frame_type": "custom_highlight",
                    "second": 1,
                    "relative_path": "highlights/101/01-001s.jpg",
                }],
            })

            frames = highlights.generate_missing_highlights_for_detail(
                detail,
                root,
                spec,
                downloader=downloader,
                batch_extractor=batch_extractor,
            )

            self.assertEqual(requested_seconds, [3])
            self.assertEqual(preserved.read_bytes(), b"preserved-jpeg")
            self.assertEqual([frame["second"] for frame in frames], [1, 3])

    def test_normalize_highlight_trends_deduplicates_and_rejects_unknown_names(self):
        highlights = load_module()

        self.assertEqual(
            highlights.normalize_highlight_trends(["点击指数", "点赞指数", "点击指数"]),
            ["点击指数", "点赞指数"],
        )
        with self.assertRaisesRegex(ValueError, "未知"):
            highlights.normalize_highlight_trends(["播放指数"])

    def test_select_candidates_keeps_cover_and_ranks_three_local_peaks(self):
        highlights = load_module()
        detail = detail_with_trends(
            {
                "trend_name": "点击指数",
                "series": [
                    {"second": 0, "value": 0},
                    {"second": 1, "value": 9},
                    {"second": 2, "value": 1},
                    {"second": 3, "value": 8},
                    {"second": 4, "value": 1},
                    {"second": 5, "value": 7},
                    {"second": 6, "value": 1},
                    {"second": 7, "value": 0},
                ],
            }
        )

        candidates = highlights.select_highlight_candidates(detail, ["点击指数"])

        self.assertEqual([item["second"] for item in candidates], [0, 1, 3, 5])
        self.assertEqual(candidates[0], {"second": 0, "is_cover": True, "reasons": [{"type": "cover"}]})
        self.assertEqual(
            candidates[1]["reasons"],
            [{"type": "local_peak", "trend_name": "点击指数", "value": 9, "rank": 1, "within_high_point": False}],
        )
        self.assertEqual([item["reasons"][0]["rank"] for item in candidates[1:]], [1, 2, 3])

    def test_select_standard_candidates_keeps_cover_and_click_top_five(self):
        highlights = load_module()
        detail = detail_with_trends(
            {
                "trend_name": "点击指数",
                "series": [
                    {"second": 0, "value": 0},
                    {"second": 1, "value": 9}, {"second": 2, "value": 0},
                    {"second": 3, "value": 8}, {"second": 4, "value": 0},
                    {"second": 5, "value": 7}, {"second": 6, "value": 0},
                    {"second": 7, "value": 6}, {"second": 8, "value": 0},
                    {"second": 9, "value": 5}, {"second": 10, "value": 0},
                    {"second": 11, "value": 4}, {"second": 12, "value": 0},
                ],
            },
            {
                "trend_name": "点赞指数",
                "series": [{"second": 2, "value": 0}, {"second": 3, "value": 99}, {"second": 4, "value": 0}],
            },
        )

        candidates = highlights.select_standard_highlight_candidates(detail)

        self.assertEqual([item["second"] for item in candidates], [0, 1, 3, 5, 7, 9])
        self.assertEqual(candidates[0]["frame_type"], "cover")
        self.assertIsNone(candidates[0]["peak_rank"])
        self.assertEqual(
            [(item["frame_type"], item["peak_rank"], item["click_value"]) for item in candidates[1:]],
            [("click_peak", 1, 9), ("click_peak", 2, 8), ("click_peak", 3, 7), ("click_peak", 4, 6), ("click_peak", 5, 5)],
        )

    def test_standard_candidates_merge_a_zero_second_click_peak_into_the_cover(self):
        highlights = load_module()
        detail = detail_with_trends(
            {
                "trend_name": "点击指数",
                "series": [
                    {"second": 0, "value": 9}, {"second": 1, "value": 0},
                    {"second": 2, "value": 8}, {"second": 3, "value": 0},
                ],
            }
        )

        candidates = highlights.select_standard_highlight_candidates(detail)

        self.assertEqual([candidate["second"] for candidate in candidates], [0, 2])
        self.assertEqual(candidates[0]["frame_type"], "cover")
        self.assertEqual(candidates[0]["peak_rank"], 1)
        self.assertEqual(candidates[0]["click_value"], 9)
        self.assertEqual([reason["type"] for reason in candidates[0]["reasons"]], ["cover", "local_peak"])

    def test_select_candidates_uses_earliest_second_for_peak_plateau(self):
        highlights = load_module()
        detail = detail_with_trends(
            {
                "trend_name": "互动指数",
                "series": [
                    {"second": 1, "value": 1},
                    {"second": 2, "value": 4},
                    {"second": 2, "value": 5},
                    {"second": 3, "value": 5},
                    {"second": 4, "value": 1},
                ],
            }
        )

        candidates = highlights.select_highlight_candidates(detail, ["互动指数"])

        self.assertEqual([item["second"] for item in candidates], [0, 2])
        self.assertEqual(candidates[1]["reasons"][0]["value"], 5)

    def test_select_candidates_merges_same_second_across_metrics(self):
        highlights = load_module()
        detail = detail_with_trends(
            {
                "trend_name": "点击指数",
                "series": [{"second": 4, "value": 1}, {"second": 5, "value": 6}, {"second": 6, "value": 1}],
            },
            {
                "trend_name": "点赞指数",
                "series": [{"second": 4, "value": 1}, {"second": 5, "value": 4}, {"second": 6, "value": 1}],
            },
        )

        candidates = highlights.select_highlight_candidates(detail, ["点击指数", "点赞指数"])

        self.assertEqual([item["second"] for item in candidates], [0, 5])
        self.assertEqual(
            candidates[1]["reasons"],
            [
                {"type": "local_peak", "trend_name": "点击指数", "value": 6, "rank": 1, "within_high_point": False},
                {"type": "local_peak", "trend_name": "点赞指数", "value": 4, "rank": 1, "within_high_point": False},
            ],
        )

    def test_select_candidates_marks_named_high_point_membership(self):
        highlights = load_module()
        detail = detail_with_trends(
            {
                "trend_name": "评论指数",
                "series": [{"second": 4, "value": 1}, {"second": 5, "value": 3}, {"second": 6, "value": 1}],
            },
            high_points=[
                {"trend_name": "评论指数", "start_sec": 5, "end_sec": 5},
                {"trend_name": "点击指数", "start_sec": 5, "end_sec": 5},
            ],
        )

        candidates = highlights.select_highlight_candidates(detail, ["评论指数"])

        self.assertTrue(candidates[1]["reasons"][0]["within_high_point"])

    def test_generate_highlights_writes_manifest_and_continues_after_one_frame_failure(self):
        highlights = load_module()

        class Downloader:
            def __call__(self, _url, destination):
                Path(destination).write_bytes(b"video")

        class Extractor:
            def __call__(self, _video_path, second, destination, *, ffmpeg_bin=None):
                if second == 0:
                    raise highlights.HighlightFrameError("broken cover")
                Path(destination).write_bytes(b"jpeg")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = highlights.generate_highlights(
                [
                    {
                        "material_id": "101",
                        "video_url": "https://video.example/101.mp4",
                        "trend_series": [
                            {
                                "trend_name": "点击指数",
                                "series": [
                                    {"second": 1, "value": 1},
                                    {"second": 2, "value": 4},
                                    {"second": 3, "value": 1},
                                ],
                            }
                        ],
                    }
                ],
                ["点击指数"],
                root,
                downloader=Downloader(),
                frame_extractor=Extractor(),
            )

            manifest = json.loads(
                (root / "highlights-manifest.json").read_text(encoding="utf-8")
            )
            self.assertFalse(result["101"][0]["available"])
            self.assertEqual(result["101"][0]["failure_reason"], "extract_failed")
            self.assertTrue(result["101"][1]["available"])
            self.assertTrue((root / result["101"][1]["relative_path"]).is_file())
            self.assertEqual(
                manifest["materials"][0]["frames"][0]["failure_reason"],
                "extract_failed",
            )

    def test_generate_highlights_marks_missing_video_url_without_raising(self):
        highlights = load_module()
        with tempfile.TemporaryDirectory() as directory:
            result = highlights.generate_highlights(
                [{"material_id": "101", "video_url": "", "trend_series": []}],
                ["评论指数"],
                directory,
            )

        self.assertFalse(result["101"][0]["available"])
        self.assertEqual(result["101"][0]["failure_reason"], "missing_video_url")

    def test_standard_highlights_reuse_existing_frames_when_video_download_fails(self):
        highlights = load_module()

        def failing_downloader(_url, _destination):
            raise highlights.HighlightFrameError("expired")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "highlights" / "101" / "01-000s.jpg"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"jpeg")

            result = highlights.generate_standard_highlights(
                [{"material_id": "101", "video_url": "https://video.example/101.mp4", "trend_series": []}],
                root,
                downloader=failing_downloader,
            )

        self.assertTrue(result["101"][0]["available"])
        self.assertEqual(result["101"][0]["relative_path"], "highlights/101/01-000s.jpg")
        self.assertEqual(result["101"][0]["frame_source"], "reused_local_extracted_frame")

    def test_single_material_standard_highlights_reuses_complete_manifest(self):
        highlights = load_module()
        detail = {
            "material_id": "101",
            "video_url": "https://video.example/101.mp4",
            "trend_series": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "highlights" / "101" / "01-000s.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"jpeg")
            highlights.write_highlights_manifest(
                root,
                {
                    "101": [
                        {
                            "frame_ref": "highlight:101:cover:0",
                            "second": 0,
                            "is_cover": True,
                            "frame_type": "cover",
                            "peak_rank": None,
                            "click_value": None,
                            "reasons": [{"type": "cover"}],
                            "available": True,
                            "relative_path": "highlights/101/01-000s.jpg",
                        }
                    ]
                },
            )
            frames = highlights.generate_standard_highlights_for_detail(
                detail,
                root,
                downloader=lambda *_args: self.fail("unexpected video download"),
                frame_extractor=lambda *_args, **_kwargs: self.fail("unexpected frame extraction"),
            )

        self.assertTrue(frames[0]["available"])
        self.assertEqual(frames[0]["frame_source"], "reused_local_extracted_frame")

    def test_details_missing_standard_highlights_detects_missing_frame_file(self):
        highlights = load_module()
        details = [
            {"material_id": "101", "trend_series": []},
            {"material_id": "202", "trend_series": []},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            highlights.write_highlights_manifest(
                root,
                {
                    "101": [
                        {
                            "frame_ref": "highlight:101:cover:0",
                            "second": 0,
                            "is_cover": True,
                            "frame_type": "cover",
                            "available": True,
                            "relative_path": "highlights/101/missing.jpg",
                        }
                    ]
                },
            )
            missing = highlights.details_missing_standard_highlights(details, root)

        self.assertEqual([item["material_id"] for item in missing], ["101", "202"])

    def test_generate_highlights_reuses_existing_frame_when_extraction_fails(self):
        highlights = load_module()

        def downloader(_url, destination):
            Path(destination).write_bytes(b"video")

        def failing_extractor(_video_path, _second, _destination, *, ffmpeg_bin=None):
            raise highlights.HighlightFrameError("cannot seek")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "highlights" / "101" / "01-000s.jpg"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"jpeg")

            result = highlights.generate_highlights(
                [{"material_id": "101", "video_url": "https://video.example/101.mp4", "trend_series": []}],
                ["点击指数"],
                root,
                downloader=downloader,
                frame_extractor=failing_extractor,
            )

        self.assertTrue(result["101"][0]["available"])
        self.assertEqual(result["101"][0]["frame_source"], "reused_local_extracted_frame")

    def test_extract_frames_batch_uses_one_exact_decode_graph_with_limited_threads(self):
        highlights = load_module()

        def run(command, **_kwargs):
            for index, token in enumerate(command):
                if token == "image2":
                    Path(command[index + 1]).write_bytes(b"\xff\xd8ok\xff\xd9")
            return mock.Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requests = [
                {"second": 0, "destination": root / "cover.jpg"},
                {"second": 2, "destination": root / "peak.jpg"},
            ]
            with mock.patch.object(highlights, "_resolve_ffmpeg", return_value="ffmpeg"), \
                 mock.patch.object(highlights.subprocess, "run", side_effect=run) as invoke:
                targets = highlights.extract_frames_batch(root / "source.mp4", requests)

            command = invoke.call_args_list[0].args[0]
            graph = command[command.index("-filter_complex") + 1]
            self.assertEqual(command.count("-i"), 1)
            self.assertEqual(command[command.index("-threads") + 1], "1")
            self.assertEqual(command[command.index("-filter_threads") + 1], "1")
            self.assertIn("[0:v]split=2[s0][s1]", graph)
            self.assertIn("[s0]trim=start=0,setpts=PTS-STARTPTS[out0]", graph)
            self.assertIn("[s1]trim=start=2,setpts=PTS-STARTPTS[out1]", graph)
            self.assertEqual(command.count("-frames:v"), 2)
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(targets, [root / "cover.jpg", root / "peak.jpg"])
            self.assertTrue(all(path.is_file() for path in targets))

    def test_extract_frame_allows_deep_seconds_for_1080p_vertical_fixture(self):
        highlights = load_module()
        observed_timeouts = []
        source_detail = json.loads(
            (
                ROOT
                / "runs/food-beverage-2026-0810-0820/normalized/detail-records/"
                "7668663443726172214.json"
            ).read_text(encoding="utf-8")
        )
        deep_seconds = {
            point["second"]
            for trend in source_detail["trend_series"]
            if trend["trend_name"] == "点击指数"
            for point in trend["series"]
            if point["second"] in {31, 47}
        }
        self.assertEqual(deep_seconds, {31, 47})

        def run(command, *, timeout, **_kwargs):
            observed_timeouts.append(timeout)
            if timeout == highlights.VIDEO_DOWNLOAD_TIMEOUT_SECONDS:
                raise subprocess.TimeoutExpired(command, timeout)
            Path(command[-1]).write_bytes(b"\xff\xd8fixture\xff\xd9")
            return mock.Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "fixture-1080x1920-48s.mp4"
            video.write_bytes(b"fixture video")
            with mock.patch.object(highlights, "_resolve_ffmpeg", return_value="ffmpeg"), \
                 mock.patch.object(highlights.subprocess, "run", side_effect=run):
                for second in (31, 47):
                    target = root / f"frame-{second}.jpg"
                    highlights.extract_frame(video, second, target)
                    self.assertTrue(target.is_file())

        self.assertEqual(highlights.VIDEO_DOWNLOAD_TIMEOUT_SECONDS, 30)
        self.assertEqual(observed_timeouts, [120, 120])

    def test_extract_frames_batch_allows_31s_and_47s_for_deep_vertical_fixture(self):
        highlights = load_module()
        observed_timeouts = []

        def run(command, *, timeout, **_kwargs):
            observed_timeouts.append(timeout)
            if timeout == highlights.VIDEO_DOWNLOAD_TIMEOUT_SECONDS:
                raise subprocess.TimeoutExpired(command, timeout)
            for index, token in enumerate(command):
                if token == "image2":
                    Path(command[index + 1]).write_bytes(b"\xff\xd8fixture\xff\xd9")
            return mock.Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "fixture-1080x1920-48s.mp4"
            video.write_bytes(b"fixture video")
            requests = [
                {"second": 31, "destination": root / "frame-31.jpg"},
                {"second": 47, "destination": root / "frame-47.jpg"},
            ]
            with mock.patch.object(highlights, "_resolve_ffmpeg", return_value="ffmpeg"), \
                 mock.patch.object(highlights.subprocess, "run", side_effect=run):
                targets = highlights.extract_frames_batch(video, requests)
                self.assertTrue(all(path.is_file() for path in targets))

        self.assertEqual(observed_timeouts, [120])
        self.assertEqual(targets, [root / "frame-31.jpg", root / "frame-47.jpg"])

    def test_failed_deep_frame_is_not_published_and_keeps_ffmpeg_diagnostic(self):
        highlights = load_module()

        def downloader(_url, destination):
            Path(destination).write_bytes(b"fixture video")

        def failed_batch(*_args, **_kwargs):
            raise highlights.HighlightFrameError(
                "ffmpeg batch frame extraction timed out after 120 seconds"
            )

        def frame_extractor(_video, second, destination, *, ffmpeg_bin=None):
            if second == 47:
                raise highlights.HighlightFrameError(
                    "ffmpeg frame extraction timed out after 120 seconds"
                )
            Path(destination).write_bytes(b"\xff\xd8fixture\xff\xd9")

        detail = {
            "material_id": "7668663443726172214",
            "video_url": "https://video.example/fixture.mp4",
            "trend_series": [{
                "trend_name": "点击指数",
                "series": [
                    {"second": 31, "value": 10},
                    {"second": 47, "value": 9},
                ],
            }],
        }
        spec = {
            "include_cover": False,
            "metrics": {"点击指数": {"strategy": "top_values", "limit": 2}},
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = highlights.generate_highlights_for_detail(
                detail,
                root,
                spec,
                downloader=downloader,
                frame_extractor=frame_extractor,
                batch_extractor=failed_batch,
            )
            failed_target = root / "highlights" / detail["material_id"] / "02-047s.jpg"

            self.assertTrue(frames[0]["available"])
            self.assertFalse(frames[1]["available"])
            self.assertEqual(frames[1]["failure_reason"], "extract_failed")
            self.assertIn("timed out after 120 seconds", frames[1]["failure_detail"])
            self.assertFalse(failed_target.exists())
            self.assertFalse(any(root.rglob("*.part")))

    def test_validate_jpeg_rejects_empty_and_truncated_files(self):
        highlights = load_module()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.jpg"
            empty.touch()
            truncated = root / "truncated.jpg"
            truncated.write_bytes(b"\xff\xd8not-complete")

            with self.assertRaisesRegex(highlights.HighlightFrameError, "empty"):
                highlights._validate_jpeg(empty)
            with self.assertRaisesRegex(highlights.HighlightFrameError, "JPEG markers"):
                highlights._validate_jpeg(truncated)

    def test_standard_highlights_extract_all_frames_in_one_batch_call(self):
        highlights = load_module()
        calls = []

        def downloader(_url, destination):
            Path(destination).write_bytes(b"video")

        def batch_extractor(_video, requests, *, ffmpeg_bin=None):
            calls.append(requests)
            for request in requests:
                Path(request["destination"]).write_bytes(b"\xff\xd8ok\xff\xd9")

        detail = {
            "material_id": "101",
            "video_url": "https://video.example/101.mp4",
            "trend_series": [{
                "trend_name": "点击指数",
                "series": [
                    {"second": 0, "value": 0}, {"second": 1, "value": 9},
                    {"second": 2, "value": 0}, {"second": 3, "value": 8},
                    {"second": 4, "value": 0}, {"second": 5, "value": 7},
                    {"second": 6, "value": 0}, {"second": 7, "value": 6},
                    {"second": 8, "value": 0}, {"second": 9, "value": 5},
                    {"second": 10, "value": 0},
                ],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            frames = highlights.generate_standard_highlights_for_detail(
                detail, directory, downloader=downloader, batch_extractor=batch_extractor
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual([request["second"] for request in calls[0]], [0, 1, 3, 5, 7, 9])
        self.assertTrue(all(frame["available"] for frame in frames))

    def test_batch_extraction_failure_falls_back_to_each_frame(self):
        highlights = load_module()
        extracted_seconds = []

        def downloader(_url, destination):
            Path(destination).write_bytes(b"video")

        def failed_batch(*_args, **_kwargs):
            raise highlights.HighlightFrameError("batch failed")

        def frame_extractor(_video, second, destination, *, ffmpeg_bin=None):
            extracted_seconds.append(second)
            Path(destination).write_bytes(b"\xff\xd8ok\xff\xd9")

        detail = {"material_id": "101", "video_url": "https://video.example/101.mp4", "trend_series": []}
        with tempfile.TemporaryDirectory() as directory:
            frames = highlights.generate_standard_highlights_for_detail(
                detail,
                directory,
                downloader=downloader,
                frame_extractor=frame_extractor,
                batch_extractor=failed_batch,
            )

        self.assertEqual(extracted_seconds, [0])
        self.assertTrue(frames[0]["available"])

    def test_download_video_rejects_response_larger_than_limit(self):
        highlights = load_module()

        class Response:
            headers = {"Content-Length": "5"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield b"12345"

            def close(self):
                return None

        class Session:
            def get(self, _url, *, stream, timeout):
                self.stream = stream
                self.timeout = timeout
                return Response()

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(highlights.HighlightFrameError, "maximum size"):
                highlights.download_video(
                    "https://video.example/a.mp4",
                    Path(directory) / "a.mp4",
                    session=Session(),
                    max_bytes=4,
                )

    def test_download_error_diagnostic_redacts_signed_url_query(self):
        highlights = load_module()

        class Session:
            def get(self, url, *, stream, timeout):
                raise RuntimeError(
                    f"request failed for {url}?token=secret-token&sig=secret-signature"
                )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(highlights.HighlightFrameError) as raised:
                highlights.download_video(
                    "https://video.example/a.mp4?token=source-token",
                    Path(directory) / "a.mp4",
                    session=Session(),
                )

        message = str(raised.exception)
        self.assertIn("video download failed", message)
        self.assertNotIn("source-token", message)
        self.assertNotIn("secret-token", message)
        self.assertNotIn("secret-signature", message)

    def test_resolve_ffmpeg_uses_imageio_before_system_path(self):
        highlights = load_module()

        resolved = highlights._resolve_ffmpeg(
            environ={},
            imageio_resolver=lambda: "/tmp/imageio-ffmpeg",
            which=lambda _name: self.fail("PATH lookup must not run after imageio resolves"),
        )

        self.assertEqual(resolved, "/tmp/imageio-ffmpeg")

    def test_resolve_ffmpeg_falls_back_to_system_path_after_imageio_failure(self):
        highlights = load_module()

        resolved = highlights._resolve_ffmpeg(
            environ={},
            imageio_resolver=lambda: (_ for _ in ()).throw(RuntimeError("imageio unavailable")),
            which=lambda name: "/usr/local/bin/ffmpeg" if name == "ffmpeg" else None,
        )

        self.assertEqual(resolved, "/usr/local/bin/ffmpeg")


if __name__ == "__main__":
    unittest.main()
