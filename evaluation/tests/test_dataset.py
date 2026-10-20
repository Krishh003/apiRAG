import copy
import tempfile
import unittest
from pathlib import Path

from evaluation.dataset import load_dataset, read_jsonl, validate, write_jsonl


class DatasetTests(unittest.TestCase):
    def test_failed_checkpoint_preserves_previous_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'predictions.jsonl'
            original = [{'id': 'saved'}]
            write_jsonl(path, original)
            with self.assertRaises(ValueError):
                write_jsonl(path, [{'id': 'new'}, {'score': float('nan')}])
            self.assertEqual(read_jsonl(path), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def setUp(self):
        self.docs, self.questions = load_dataset()

    def test_coverage_and_ids(self):
        self.assertEqual(len(self.questions), 100)
        self.assertEqual(len(self.docs), 25)
        validate(self.docs, self.questions)
        self.assertEqual({q['mode'] for q in self.questions}, {'lookup', 'planning', 'comparison', 'advisory'})

    def test_dangling_label_rejected(self):
        questions = copy.deepcopy(self.questions)
        questions[0]['relevance']['missing'] = 1
        with self.assertRaises(ValueError):
            validate(self.docs, questions)

    def test_absent_answer_must_not_have_relevance(self):
        questions = copy.deepcopy(self.questions)
        questions[0]['answerable'] = False
        with self.assertRaises(ValueError):
            validate(self.docs, questions)

    def test_private_document_rejected(self):
        docs = copy.deepcopy(self.docs)
        docs[0]['entry']['is_internal'] = True
        with self.assertRaises(ValueError):
            validate(docs, self.questions)

    def test_empty_question_supported(self):
        questions = copy.deepcopy(self.questions)
        questions[-1]['question'] = ''
        validate(self.docs, questions)


if __name__ == '__main__':
    unittest.main()
