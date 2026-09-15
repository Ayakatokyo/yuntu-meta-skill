import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from scripts import collector


ROOT = Path(__file__).resolve().parent
RUNTIME_ENV = {
    "ENV_BACKEND_HOST": "https://gateway.example/api",
    "YUCE_AUTHORIZATION": "test-auth",
    "YCSESSIONID": "test-cookie",
}


class CollectorTests(unittest.TestCase):
    def _fact_manifest(self):
        return {
            "coverage": {
                "ranking_records": 2,
                "detail_records": 1,
                "script_records": 1,
                "highlight_materials": 1,
                "available_highlight_frames": 1,
            }
        }

    def test_validate_prints_resolved_configuration_without_rpa(self):
        with tempfile.TemporaryDirectory() as directory:
            output = []
            with mock.patch("builtins.print", side_effect=lambda value: output.append(value)):
                status = collector.main([
                    "validate",
                    "--query-spec", str(ROOT / "fixtures/query-spec.json"),
                    "--highlight-spec", str(ROOT / "fixtures/highlight-spec.json"),
                ])
        self.assertEqual(status, 0)
        payload = json.loads(output[0])
        self.assertEqual(payload["query"]["collection"]["target_top_n"], 2)
        self.assertEqual(payload["highlights"]["metrics"]["点赞指数"]["strategy"], "top_values")

    def test_collector_has_analyze_command(self):
        commands = collector._parser()._subparsers._group_actions[0].choices
        self.assertIn("analyze", commands)

    def test_runtime_config_does_not_treat_codex_session_as_gateway_login(self):
        with self.assertRaisesRegex(collector.RpaConnectorError, "YUCE_SESSION_ID or YCSESSIONID"):
            collector.runtime_config({
                "ENV_BACKEND_HOST": "https://gateway.example/",
                "YUCE_AUTHORIZATION": "auth",
                "CODEX_SESSION_ID": "codex-session",
            })

    def test_runtime_config_keeps_platform_cookie_when_provided(self):
        _, _, session_id, cookies = collector.runtime_config({
            "ENV_BACKEND_HOST": "https://gateway.example",
            "YUCE_AUTHORIZATION": "auth",
            "YCSESSIONID": "browser-session",
        })
        self.assertEqual(session_id, "browser-session")
        self.assertEqual(cookies, {"YCSESSIONID": "browser-session"})

    def test_gateway_login_failure_is_classified_without_assuming_login_source(self):
        with self.assertRaisesRegex(collector.RpaConnectorError, "authentication_failed"):
            collector._require_successful_result({
                "success": False,
                "code": "500",
                "msg": "鉴权失败：用户未登录",
            })

    def test_detail_connector_uses_live_async_submit_contract(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        session = mock.Mock()
        session.post.side_effect = [
            Response({
                "success": True,
                "data": [{
                    "connectorCode": "rpa.conn.juliang.yt.industry.content.rankings.details",
                    "platformCode": "YT_DYNAMIC_PLATFORM",
                    "inParamJsonSchemaText": None,
                    "inParamList": [
                        {"param": "material_id", "isRequired": True, "dataTypeEnum": "STRING"},
                        {"param": "date_type", "isRequired": True, "dataTypeEnum": "STRING"},
                        {"param": "custom_start_date", "isRequired": False, "dataTypeEnum": "STRING"},
                        {"param": "custom_end_date", "isRequired": False, "dataTypeEnum": "STRING"},
                    ],
                    "outParamList": [],
                }],
            }),
            Response({"success": True, "data": {"task_group_id": "tg-101"}}),
        ]
        environment = {
            "ENV_BACKEND_HOST": "https://gateway.example/",
            "YUCE_AUTHORIZATION": "auth",
            "YUCE_SESSION_ID": "session",
        }
        task_group_id = collector.submit_fetch_task(
            "detail", "shop-1",
            {"material_id": "101", "date_type": "LAST_7_DAYS"},
            environ=environment, session=session,
        )

        self.assertEqual(task_group_id, "tg-101")
        _, kwargs = session.post.call_args
        url = session.post.call_args.args[0]
        self.assertTrue(url.endswith("/adg/v1/agent/fetch/tasks"))
        self.assertEqual(
            kwargs["json"]["function_code"],
            "rpa.conn.juliang.yt.industry.content.rankings.details",
        )
        self.assertEqual(kwargs["json"]["business_params"]["date_type"], "LAST_7_DAYS")
        self.assertNotIn("date_range_type", kwargs["json"]["business_params"])
        self.assertEqual(kwargs["json"]["platform"], "YT_DYNAMIC_PLATFORM")

    def test_wait_fetch_task_polls_until_completed_and_rejects_old_date_key(self):
        class Response:
            def __init__(self, status):
                self.status = status

            def raise_for_status(self):
                return None

            def json(self):
                return {"success": True, "data": {"status": self.status, "payload": []}}

        session = mock.Mock()
        session.post.side_effect = [Response("pending"), Response("completed")]
        environment = {
            "ENV_BACKEND_HOST": "https://gateway.example/",
            "YUCE_AUTHORIZATION": "auth",
            "YUCE_SESSION_ID": "session",
        }
        with mock.patch.object(collector.time, "sleep") as sleep:
            result = collector.wait_fetch_task(
                "tg-101", environ=environment, session=session,
                timeout_seconds=2, poll_interval_seconds=1,
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(session.post.call_count, 2)
        sleep.assert_called()
        with self.assertRaisesRegex(collector.RpaConnectorError, "date_range_type"):
            collector.validate_detail_business_params(
                {"material_id": "101", "date_range_type": "LAST_7_DAYS"}
            )

    def test_list_connector_reads_live_contract_and_uses_async_tasks(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        session = mock.Mock()
        session.post.side_effect = [
            Response({
                "success": True,
                "data": [{
                    "connectorCode": "rpa.conn.juliang.yt.industry.content.rankings.list",
                    "platformCode": "YT_DYNAMIC_PLATFORM",
                    "inParamJsonSchemaText": json.dumps({
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "properties": {"industry": {"type": "string"}},
                        "required": ["industry"],
                        "additionalProperties": False,
                    }),
                    "inParamList": [{"param": "must_not_be_used"}],
                    "outParamList": [],
                }],
            }),
            Response({"success": True, "data": {"task_group_id": "tg-list"}}),
            Response({
                "success": True,
                "data": {"status": "completed", "payload": [{"material_id": "101"}]},
            }),
        ]
        environment = {
            "ENV_BACKEND_HOST": "https://gateway.example/",
            "YUCE_AUTHORIZATION": "auth",
            "YUCE_SESSION_ID": "session",
        }

        with mock.patch.object(collector.time, "sleep"):
            result = collector.invoke_list(
                "shop-1", {"industry": "食品饮料"}, environ=environment, session=session
            )

        self.assertEqual(result["payload"][0]["material_id"], "101")
        urls = [call.args[0] for call in session.post.call_args_list]
        self.assertTrue(urls[0].endswith("/dcConnector/v3/listByConnectorCode"))
        self.assertTrue(urls[1].endswith("/adg/v1/agent/fetch/tasks"))
        self.assertTrue(urls[2].endswith("/adg/v1/agent/fetch/tasks/status"))
        self.assertEqual(
            session.post.call_args_list[1].kwargs["json"]["function_code"],
            "rpa.conn.juliang.yt.industry.content.rankings.list",
        )
        self.assertEqual(
            session.post.call_args_list[1].kwargs["json"]["platform"],
            "YT_DYNAMIC_PLATFORM",
        )

    def test_wait_fetch_task_rejects_unknown_remote_status(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"success": True, "data": {"status": "queued"}}

        session = mock.Mock()
        session.post.return_value = Response()
        environment = {
            "ENV_BACKEND_HOST": "https://gateway.example/",
            "YUCE_AUTHORIZATION": "auth",
            "YUCE_SESSION_ID": "session",
        }
        with mock.patch.object(collector.time, "sleep"):
            with self.assertRaisesRegex(collector.RpaConnectorError, "unknown status"):
                collector.wait_fetch_task(
                    "tg-101", environ=environment, session=session,
                    timeout_seconds=2, poll_interval_seconds=1,
                )

    def test_render_overview_does_not_initialize_collection_or_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            with mock.patch.object(collector, "write_overview", return_value={"status": "succeeded"}) as render, \
                 mock.patch.object(collector, "fetch_batch", side_effect=AssertionError("must not collect")), \
                 mock.patch.object(collector, "prepare_fact_selection_handoff", side_effect=AssertionError("must not analyze")), \
                 mock.patch("builtins.print") as output:
                status = collector.main(["render-overview", "--run-dir", str(run_dir)])
        self.assertEqual(status, 0)
        render.assert_called_once()
        args, kwargs = render.call_args
        self.assertEqual(args[0], run_dir)
        self.assertEqual(args[1], run_dir / "overview")
        self.assertTrue(str(args[2]).endswith("config/yuntu-material-field-registry-v1.json"))
        output.assert_called_once()

    def test_analyze_writes_report_and_structured_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "facts").mkdir()
            manifest = {
                "schema_version": 1, "run_id": "run-1", "source_artifacts": [],
                "packages": {
                    "material_ranking": {"path": "facts/material-ranking.json", "record_count": 1, "source_paths": ["normalized/list-records.json"]},
                },
            }
            (root / "facts/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "facts/material-ranking.json").write_text(json.dumps({
                "schema_version": 1, "records": [{"material_id": "101", "rank": 1}],
            }), encoding="utf-8")
            spec_path = root / "analysis-spec.json"
            spec_path.write_text(json.dumps({
                "analysis_id": "analysis-1", "run_id": "run-1",
                "sections": ["material_ranking"], "business_question": "比较素材表现",
                "filters": {"rank_range": [1, 1]},
            }), encoding="utf-8")
            output = root / "analysis.md"
            result_path = root / "model-result.json"
            result_path.write_text(json.dumps({
                "section": "material_ranking",
                "findings": [{
                    "claim": "排名为1",
                    "type": "fact",
                    "confidence": "high",
                    "fact_refs": ["facts/material-ranking.json#/records/0"],
                }],
            }), encoding="utf-8")
            status = collector.main([
                "analyze", "--run-dir", str(root), "--spec", str(spec_path),
                "--analysis-result", str(result_path), "--output", str(output),
            ])

            self.assertEqual(status, 0)
            self.assertTrue(output.is_file())
            self.assertTrue((root / "analysis.analysis-result.json").is_file())
            self.assertIn("一、核心结论", output.read_text(encoding="utf-8"))

    def _write_phase_two_run(self, root, status="ready_for_analysis"):
        (root / "facts").mkdir()
        packages = {}
        for section, filename in {
            "material_ranking": "material-ranking.json",
            "audience": "audience.json",
            "script": "script.json",
            "highlight_frames": "highlight-frames.json",
        }.items():
            records = [{"material_id": "101", "rank": 1}] if section != "script" and section != "highlight_frames" else [{"material_id": "101"}]
            (root / "facts" / filename).write_text(
                json.dumps({"schema_version": 1, "records": records}), encoding="utf-8"
            )
            packages[section] = {"path": f"facts/{filename}", "record_count": 1}
        (root / "facts/manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "run_id": "run-1",
            "source_artifacts": [],
            "packages": packages,
        }), encoding="utf-8")
        (root / "run-summary.json").write_text(json.dumps({
            "runId": "run-1", "status": status,
        }), encoding="utf-8")

    def test_analyze_accepts_phase_two_input_and_marks_analysis_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_phase_two_run(root)
            output = root / "analysis.md"
            result_path = root / "model-result.json"
            result_path.write_text(json.dumps({"results": [
                {
                    "section": "material_ranking",
                    "findings": [{
                        "claim": "排名为1",
                        "type": "fact",
                        "confidence": "high",
                        "fact_refs": ["facts/material-ranking.json#/records/0"],
                    }],
                },
                {"section": "audience", "findings": [], "gaps": ["数据不足"]},
            ]}), encoding="utf-8")
            with mock.patch.object(collector, "fetch_batch") as fetch, \
                    mock.patch.object(collector, "build_fact_packages") as build:
                status = collector.main([
                    "analyze", "--run-dir", str(root),
                    "--input", json.dumps({
                        "run_id": "run-1",
                        "sections": ["material_ranking", "audience"],
                        "material_filter": {"rank_range": [1, 1]},
                        "business_question": "比较素材和人群",
                    }, ensure_ascii=False),
                    "--analysis-result", str(result_path),
                    "--output", str(output),
                ])

            self.assertEqual(status, 0)
            self.assertTrue(output.is_file())
            self.assertFalse(fetch.called)
            self.assertFalse(build.called)
            summary = json.loads((root / "run-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["workflow"]["stage"], "analysis_completed")

    def test_analyze_accepts_only_explicitly_confirmed_default_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_phase_two_run(root)
            result_path = root / "model-result.json"
            result_path.write_text(json.dumps({"section": "audience", "findings": [], "gaps": ["数据不足"]}), encoding="utf-8")
            output = root / "analysis.md"

            status = collector.main([
                "analyze", "--run-dir", str(root),
                "--input", json.dumps({
                    "sections": ["audience"],
                    "business_question": "系统默认商业问题",
                    "business_question_source": "user_confirmed_default",
                    "user_confirmed": True,
                }, ensure_ascii=False),
                "--analysis-result", str(result_path), "--output", str(output),
            ])

            self.assertEqual(status, 0)
            self.assertTrue(output.is_file())
            request = json.loads(output.with_suffix(".model-analysis-request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["host_context"]["analysis_spec"]["business_question_source"], "user_confirmed_default")
            self.assertTrue(request["host_context"]["analysis_spec"]["user_confirmed"])

    def test_analyze_without_model_result_persists_handoff_without_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_phase_two_run(root)
            output = root / "analysis.md"
            with mock.patch("builtins.print") as printer:
                status = collector.main([
                    "analyze", "--run-dir", str(root),
                    "--input", json.dumps({
                        "sections": ["material_ranking"],
                        "material_filter": {"rank_range": [1, 1]},
                        "business_question": "比较素材",
                    }, ensure_ascii=False),
                    "--output", str(output),
                ])

            self.assertEqual(status, 0)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".analysis-result.json").exists())
            request_path = output.with_suffix(".model-analysis-request.json")
            self.assertTrue(request_path.is_file())
            request = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertEqual(request["host_context"]["response_schema"], "AnalysisResult")
            self.assertEqual(request["host_context"]["analysis_spec"]["business_question"], "比较素材")
            response = json.loads(printer.call_args.args[0])
            self.assertEqual(response["status"], "awaiting_model_analysis")
            self.assertEqual(response["host_handoff"]["protocol"], "yuntu-current-conversation-model-v2")
            self.assertEqual(response["model_analysis_request_path"], str(request_path))
            self.assertEqual(json.loads((root / "run-summary.json").read_text(encoding="utf-8"))["status"], "ready_for_analysis")

    def test_analyze_selection_only_returns_input_required_without_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_phase_two_run(root)
            output = root / "analysis.md"
            with mock.patch("builtins.print") as printer:
                status = collector.main([
                    "analyze", "--run-dir", str(root),
                    "--input", json.dumps({"sections": ["material_ranking"]}),
                    "--output", str(output),
                ])

            self.assertEqual(status, 0)
            response = json.loads(printer.call_args.args[0])
            self.assertEqual(response["status"], "analysis_input_required")
            self.assertEqual(response["stage"], "ready_for_analysis")
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".prompt-packet.json").exists())
            self.assertFalse(output.with_suffix(".model-analysis-request.json").exists())
            self.assertFalse(output.with_suffix(".analysis-result.json").exists())
            self.assertFalse(output.with_suffix(".analysis-error.json").exists())
            self.assertEqual(json.loads((root / "run-summary.json").read_text(encoding="utf-8"))["status"], "ready_for_analysis")

    def test_analyze_filter_only_returns_input_required_without_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_phase_two_run(root)
            output = root / "analysis.md"
            with mock.patch("builtins.print") as printer:
                status = collector.main([
                    "analyze", "--run-dir", str(root),
                    "--input", json.dumps({"material_filter": {"rank_range": [1, 1]}}),
                    "--output", str(output),
                ])

            self.assertEqual(status, 0)
            response = json.loads(printer.call_args.args[0])
            self.assertEqual(response["status"], "analysis_input_required")
            self.assertEqual(response["stage"], "ready_for_analysis")
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".prompt-packet.json").exists())
            self.assertFalse(output.with_suffix(".model-analysis-request.json").exists())
            self.assertFalse(output.with_suffix(".analysis-result.json").exists())
            self.assertFalse(output.with_suffix(".analysis-error.json").exists())

    def test_analyze_rejects_phase_two_input_before_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_phase_two_run(root, status="partial")
            output = root / "analysis.md"
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    collector.main([
                        "analyze", "--run-dir", str(root),
                        "--input", json.dumps({
                            "sections": ["material_ranking"],
                            "material_filter": {"rank_range": [1, 1]},
                            "business_question": "比较素材",
                        }, ensure_ascii=False),
                        "--output", str(output),
                    ])

            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(output.exists())

    def test_analyze_rejects_legacy_spec_before_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_phase_two_run(root, status="collecting")
            spec_path = root / "analysis-spec.json"
            spec_path.write_text(json.dumps({
                "analysis_id": "analysis-legacy",
                "run_id": "run-1",
                "sections": ["material_ranking"],
                "business_question": "比较素材",
                "filters": {"rank_range": [1, 1]},
            }), encoding="utf-8")
            output = root / "analysis.md"
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    collector.main([
                        "analyze", "--run-dir", str(root),
                        "--spec", str(spec_path), "--output", str(output),
                    ])

            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".prompt-packet.json").exists())
            self.assertFalse(output.with_suffix(".model-analysis-request.json").exists())

    def test_invalid_analysis_result_does_not_leave_run_in_analysis_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_phase_two_run(root)
            result_path = root / "invalid-result.json"
            result_path.write_text(json.dumps({
                "section": "material_ranking",
                "findings": [{
                    "claim": "invalid",
                    "type": "fact",
                    "confidence": "high",
                    "fact_refs": ["facts/material-ranking.json#/records/999"],
                }],
            }), encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    collector.main([
                        "analyze", "--run-dir", str(root),
                        "--input", json.dumps({
                            "sections": ["material_ranking"],
                            "material_filter": {"rank_range": [1, 1]},
                            "business_question": "比较素材",
                        }, ensure_ascii=False),
                        "--analysis-result", str(result_path),
                        "--output", str(root / "analysis.md"),
                    ])

            self.assertEqual(raised.exception.code, 2)
            summary = json.loads((root / "run-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "analysis_failed")
            attempts = json.loads((root / "analysis" / "analysis-attempts.json").read_text(encoding="utf-8"))
            self.assertEqual(attempts[-1]["status"], "failed")
            self.assertTrue((root / "analysis.analysis-error.json").is_file())
            self.assertFalse((root / "analysis.analysis-result.json").exists())
            error_document = json.loads((root / "analysis.analysis-error.json").read_text(encoding="utf-8"))
            self.assertEqual(error_document["code"], "analysis_result_invalid")
            self.assertTrue(error_document["errors"])
            self.assertTrue(all(set(("code", "path", "message", "suggestion")).issubset(error) for error in error_document["errors"]))

    def test_analyze_does_not_write_report_when_result_fails_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(collector, "_analysis_pipeline", side_effect=ValueError("校验失败")):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        collector.main(["analyze", "--run-dir", str(root), "--spec", str(root / "spec.json"), "--output", str(root / "analysis.md")])
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse((root / "analysis.md").exists())

    def test_analysis_outputs_are_not_published_when_staging_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "analysis.md"
            with mock.patch.object(collector, "write_json_atomically", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    collector._write_analysis_outputs("".join(str(output)), "report", {}, {})
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".analysis-result.json").exists())
            self.assertFalse(output.with_suffix(".prompt-packet.json").exists())

    def test_build_facts_dispatches_to_local_builder(self):
        captured = {}

        def fake_build_fact_packages(run_dir):
            captured["run_dir"] = run_dir
            return {
                "packages": {
                    "material_ranking": {"record_count": 2},
                    "audience": {"record_count": 2},
                    "script": {"record_count": 1},
                    "highlight_frames": {"record_count": 1},
                },
                "coverage": {
                    "ranking_records": 2,
                    "detail_records": 1,
                    "script_records": 1,
                    "highlight_materials": 1,
                    "available_highlight_frames": 1,
                },
            }

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(collector, "build_fact_packages", fake_build_fact_packages), \
                mock.patch("builtins.print") as printer:
            status = collector.main(["build-facts", "--run-dir", directory])

        self.assertEqual(status, 0)
        self.assertEqual(captured["run_dir"], directory)
        output = json.loads(printer.call_args.args[0])
        self.assertEqual(output["manifest_path"], str(Path(directory) / "facts/manifest.json"))
        self.assertEqual(output["coverage"]["ranking_records"], 2)

    @mock.patch.dict(collector.os.environ, RUNTIME_ENV, clear=True)
    def test_collect_translates_specs_into_batch_and_rpa_parameters(self):
        captured = {}

        def fake_fetch_batch(**kwargs):
            captured.update(kwargs)
            return 0

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(collector, "fetch_batch", fake_fetch_batch), \
                mock.patch.object(collector, "build_fact_packages", return_value=self._fact_manifest()) as build, \
                mock.patch("builtins.print") as printer:
            status = collector.main([
                "collect", "--shop-id", "shop-1",
                "--query-spec", str(ROOT / "fixtures/query-spec.json"),
                "--highlight-spec", str(ROOT / "fixtures/highlight-spec.json"),
                "--output-dir", directory,
            ])
            query_file_exists = (Path(directory) / "resolved-query-spec.json").is_file()
            highlight_file_exists = (Path(directory) / "resolved-highlight-spec.json").is_file()

        self.assertEqual(status, 0)
        self.assertEqual(captured["shop_id"], "shop-1")
        self.assertEqual(captured["list_params"]["ranking_limit_type"], "CTR_TOP1000")
        self.assertEqual(captured["list_params"]["time_range_type"], "LAST_7_DAYS")
        self.assertEqual(captured["detail_date_params"], {"date_type": "LAST_7_DAYS"})
        self.assertEqual(captured["target_top_n"], 2)
        self.assertEqual(captured["candidate_top_n"], 1000)
        self.assertEqual(
            captured["material_list"],
            {"filters": [], "sort": {"field": "rank", "direction": "asc"}},
        )
        self.assertNotIn("material_list", captured["list_params"])
        self.assertEqual(captured["highlight_spec"]["metrics"]["点赞指数"]["strategy"], "top_values")
        self.assertTrue(query_file_exists)
        self.assertTrue(highlight_file_exists)
        build.assert_called_once_with(directory)
        output = json.loads(printer.call_args.args[0])
        self.assertEqual(output["facts_manifest_path"], str(Path(directory) / "facts/manifest.json"))
        self.assertEqual(output["facts_coverage"]["ranking_records"], 2)

    @mock.patch.dict(collector.os.environ, RUNTIME_ENV, clear=True)
    def test_each_retry_command_builds_facts_and_reports_manifest(self):
        commands = (
            ("retry-failed", "retry_failed_batch", {"shop_id": "shop-1"}),
            ("retry-unresolved", "retry_unresolved_batch", {"shop_id": "shop-1"}),
            ("retry-highlights", "retry_highlights_batch", {}),
        )
        for command, retry_name, expected in commands:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                retry = mock.patch.object(collector, retry_name, return_value=0)
                build = mock.patch.object(collector, "build_fact_packages", return_value=self._fact_manifest())
                saved_specs = mock.patch.object(
                    collector, "_load_saved_specs", return_value=({}, {"metrics": {}})
                )
                with retry as retry_mock, build as build_mock, saved_specs, mock.patch("builtins.print") as printer:
                    argv = [command, "--output-dir", directory]
                    if "shop_id" in expected:
                        argv[1:1] = ["--shop-id", expected["shop_id"]]
                    status = collector.main(argv)

                self.assertEqual(status, 0)
                build_mock.assert_called_once_with(directory)
                output = json.loads(printer.call_args.args[0])
                self.assertEqual(output["facts_manifest_path"], str(Path(directory) / "facts/manifest.json"))

    def test_retry_highlights_uses_the_saved_spec_without_a_shop_id(self):
        captured = {}

        def fake_retry_highlights_batch(**kwargs):
            captured.update(kwargs)
            return 0

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(collector, "_load_saved_specs", return_value=({}, {"metrics": {}})), \
                mock.patch.object(collector, "retry_highlights_batch", fake_retry_highlights_batch), \
                mock.patch.object(collector, "build_fact_packages", return_value=self._fact_manifest()):
            status = collector.main([
                "retry-highlights", "--output-dir", directory,
            ])

        self.assertEqual(status, 0)
        self.assertEqual(captured, {
            "output_dir": directory,
            "highlight_spec": {"metrics": {}},
        })

    @mock.patch.dict(collector.os.environ, RUNTIME_ENV, clear=True)
    def test_facts_failure_returns_nonzero_with_facts_error(self):
        def fake_fetch_batch(**_kwargs):
            return 0

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(collector, "fetch_batch", fake_fetch_batch), \
                mock.patch.object(
                    collector, "build_fact_packages", side_effect=collector.FactPackageError("facts exploded")
                ), \
                redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as raised:
                collector.main([
                    "collect", "--shop-id", "shop-1",
                    "--query-spec", str(ROOT / "fixtures/query-spec.json"),
                    "--highlight-spec", str(ROOT / "fixtures/highlight-spec.json"),
                    "--output-dir", directory,
                ])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("facts exploded", stderr.getvalue())

    def test_retry_highlights_rejects_a_saved_spec_with_the_wrong_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "resolved-query-spec.json").write_text(
                (ROOT / "fixtures/query-spec.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (root / "resolved-highlight-spec.json").write_text(
                (ROOT / "fixtures/highlight-spec.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (root / "run-summary.json").write_text(json.dumps({
                "collectionContract": {"configurationFingerprint": "0" * 64},
            }), encoding="utf-8")
            with mock.patch.object(collector, "retry_highlights_batch") as retry:
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        collector.main(["retry-highlights", "--output-dir", directory])

        self.assertEqual(raised.exception.code, 2)
        retry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
