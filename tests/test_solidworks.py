from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from stackopt.adapters import solidworks
from stackopt.case import cad_bindings, load_case
from stackopt.diagnostics import ContractError, ExitStatus


CASE = Path(__file__).resolve().parents[1] / "examples/cad/solidworks/case.json"
BORE = next(
    binding for binding in cad_bindings(load_case(CASE), adapter="solidworks")
    if binding["logical_id"] == "bore"
)


class ComError(Exception):
    pass


class SolidWorksTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock(com_error=ComError)
        self.session.wrap.side_effect = lambda interface, obj: obj
        self.session.active_configuration.return_value.Name = "Default"
        self.part = Mock()
        self.dimension = Mock(DrivenState=2)
        self.tolerance = self.dimension.Tolerance
        self.tolerance.Type = 2
        self.tolerance.GetMinValue2.return_value = (0, -0.000025)
        self.tolerance.GetMaxValue2.return_value = (0, 0.000025)

    def test_unavailable_platform_and_dependency(self):
        for platform in ("linux", "win32"):
            with self.subTest(platform=platform), patch.object(solidworks.sys, "platform", platform):
                with patch.dict(solidworks.sys.modules, {"pythoncom": None}):
                    with self.assertRaises(ContractError) as caught:
                        solidworks.extract_active([BORE])
                self.assertEqual(caught.exception.exit_status, ExitStatus.CAD_UNAVAILABLE)
                self.assertEqual(caught.exception.diagnostic["code"], "cad.unavailable")

    def test_unavailable_running_com_object(self):
        pythoncom = Mock(com_error=ComError)
        client = Mock()
        client.GetActiveObject.side_effect = ComError
        with self.assertRaises(ContractError) as caught:
            solidworks._extract_windows([BORE], pythoncom, client)
        self.assertEqual(caught.exception.exit_status, ExitStatus.CAD_UNAVAILABLE)
        client.GetActiveObject.assert_called_once_with("SldWorks.Application")

    def test_ambiguous_occurrence_returns_one_failure_before_reading_candidates(self):
        assembly = self.session.app.ActiveDoc
        assembly.GetType.return_value = 2
        assembly.GetPathName.return_value = "assembly.sldasm"
        assembly.GetSaveFlag.return_value = False
        root = self.session.active_configuration.return_value.GetRootComponent3.return_value
        name = BORE["target"]["occurrence_path"][0]
        root.GetChildren.return_value = (Mock(Name2=name), Mock(Name2=name))

        record, = solidworks._read_assembly(self.session, [BORE])

        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["logical_id"], BORE["logical_id"])
        self.assertEqual(record["diagnostics"][0]["code"], "cad.binding_ambiguous")
        self.assertNotIn("source", record)
        for candidate in root.GetChildren.return_value:
            candidate.GetModelDoc2.assert_not_called()
        self.session.active_configuration.return_value.GetRootComponent3.assert_called_once_with(False)

    def test_document_state_uses_native_path_and_save_flag(self):
        self.part.GetPathName.return_value = ""
        self.part.GetTitle.return_value = "Part1"
        self.assertEqual(solidworks._document_ref(self.session, self.part),
                         {"id": "unsaved:Part1", "state": "unsaved"})
        self.part.GetSaveFlag.assert_not_called()
        self.part.GetPathName.return_value = "part.sldprt"
        self.part.GetSaveFlag.side_effect = ComError
        self.assertEqual(solidworks._document_ref(self.session, self.part),
                         {"id": "part.sldprt", "path": "part.sldprt", "state": "unknown"})

    def test_rejects_unsupported_occurrence_states_before_opening_part(self):
        occurrence, = BORE["target"]["occurrence_path"]
        assembly = {"id": "assembly.sldasm", "state": "saved"}
        for state, virtual in ((1, False), (2, True), (4, False), (5, False)):
            with self.subTest(state=state, virtual=virtual):
                component = Mock(ReferencedConfiguration="Default", IsVirtual=virtual)
                component.GetSuppression2.return_value = state
                record = solidworks._read_binding(
                    self.session, BORE, {occurrence: [component]}, "34.2.1", assembly, "Default",
                )
                self.assertEqual(record["status"], "failed")
                self.assertEqual(record["diagnostics"][0]["code"], "cad.binding_unavailable")
                component.GetModelDoc2.assert_not_called()

    def test_checks_dimension_type_and_feature_suppression_before_reading_nominal(self):
        occurrence, = BORE["target"]["occurrence_path"]
        component = Mock(IsVirtual=False, ReferencedConfiguration="Default")
        component.GetSuppression2.return_value = 2
        component.GetModelDoc2.return_value = self.part
        self.part.GetType.return_value = 1
        self.part.GetPathName.return_value = "part.sldprt"
        self.part.GetConfigurationNames.return_value = ("Default",)
        self.part.Parameter.return_value = self.dimension
        self.dimension.FullName = BORE["target"]["dimension_id"] + "@Part.Part"
        feature = self.dimension.GetFeatureOwner.return_value
        feature.IsSuppressed2.return_value = (True,)
        assembly = {"id": "assembly.sldasm", "state": "saved"}
        for dimension_type, expected in ((1, "cad.read_failed"), (0, "cad.binding_unavailable")):
            with self.subTest(dimension_type=dimension_type):
                self.dimension.GetType.return_value = dimension_type
                record = solidworks._read_binding(
                    self.session, BORE, {occurrence: [component]}, "34.2.1", assembly, "Default",
                )
                self.assertEqual(record["status"], "failed")
                self.assertEqual(record["diagnostics"][0]["code"], expected)
                self.assertEqual(record["source"]["occurrence_path"], [occurrence])
                self.dimension.GetSystemValue3.assert_not_called()
        self.session.configuration_names.assert_called_once_with("Default")
        feature.IsSuppressed2.assert_called_once_with(3, self.session.configuration_names.return_value)

    def test_inactive_part_configuration_cannot_qualify_tolerance(self):
        record, reason = solidworks._read_tolerance(self.session, self.part, self.dimension, "Alternate")
        self.assertEqual(record, {"status": "unavailable"})
        self.assertIn("Default", reason)
        self.assertIn("Alternate", reason)
        self.tolerance.GetMinValue2.assert_not_called()
        self.tolerance.GetMaxValue2.assert_not_called()

    def test_tolerance_needs_qualified_status_and_finite_ordered_deviations(self):
        for kind, low, high in (
            (2, (1, -0.01), (0, 0.01)),
            (3, (0, 0.02), (0, 0.01)),
            (4, (0, 0.0), (0, 0.01)),
            (4, (1, 0.0), (0, -0.01)),
            (4, (1, 0.0), (0, float("inf"))),
        ):
            with self.subTest(kind=kind, low=low, high=high):
                self.tolerance.Type = kind
                self.tolerance.GetMinValue2.return_value = low
                self.tolerance.GetMaxValue2.return_value = high
                record, reason = solidworks._read_tolerance(self.session, self.part, self.dimension, "Default")
                self.assertEqual(record, {"status": "unavailable", "native_type": kind,
                                          "native_status": {"GetMinValue2": low[0], "GetMaxValue2": high[0]}})
                self.assertTrue(reason)

    def test_tolerance_preserves_observed_status_on_partial_read_failure(self):
        self.tolerance.GetMaxValue2.side_effect = ComError
        record, reason = solidworks._read_tolerance(self.session, self.part, self.dimension, "Default")
        self.assertEqual(record, {"status": "unavailable", "native_type": 2,
                                  "native_status": {"GetMinValue2": 0}})
        self.assertTrue(reason)
