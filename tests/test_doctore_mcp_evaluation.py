from __future__ import annotations

from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
EVALUATION_PATH = ROOT / "doctore_mcp" / "evaluations" / "readonly_evaluation.xml"
WRITE_TOOLS = {"doctore_log_bet", "doctore_settle_bet"}
READ_TOOLS = {
    "doctore_parse_pinnacle_table",
    "doctore_check_data_quality",
    "doctore_load_model_prediction",
    "doctore_calculate_edge_and_stake",
    "doctore_evaluate_bet",
}


class DoctoreMcpEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = ET.parse(EVALUATION_PATH).getroot()
        cls.pairs = cls.root.findall("qa_pair")

    def test_contains_exactly_ten_qa_pairs(self) -> None:
        self.assertEqual("evaluation", self.root.tag)
        self.assertEqual(10, len(self.pairs))

    def test_each_pair_has_one_direct_comparison_answer(self) -> None:
        for index, pair in enumerate(self.pairs, start=1):
            questions = pair.findall("question")
            answers = pair.findall("answer")
            self.assertEqual(1, len(questions), msg=f"qa_pair {index}")
            self.assertEqual(1, len(answers), msg=f"qa_pair {index}")
            self.assertTrue((questions[0].text or "").strip(), msg=f"qa_pair {index}")
            answer = (answers[0].text or "").strip()
            self.assertTrue(answer, msg=f"qa_pair {index}")
            self.assertNotIn("\n", answer, msg=f"qa_pair {index} answer must be scalar")

    def test_questions_do_not_reference_write_tools(self) -> None:
        questions = "\n".join((pair.findtext("question") or "") for pair in self.pairs)
        for tool in WRITE_TOOLS:
            self.assertNotIn(tool, questions)

    def test_every_question_requires_at_least_one_read_tool(self) -> None:
        for index, pair in enumerate(self.pairs, start=1):
            question = pair.findtext("question") or ""
            used = {tool for tool in READ_TOOLS if tool in question}
            self.assertTrue(used, msg=f"qa_pair {index} does not name a read tool")


if __name__ == "__main__":
    unittest.main()
