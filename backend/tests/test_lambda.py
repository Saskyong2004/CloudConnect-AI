"""Local tests with fake AWS clients (no AWS account needed). Run: python3 -m unittest discover -s tests"""
import json, os, sys, unittest
from unittest import mock

os.environ.update(GEMINI_API_KEY="test-key", ADMIN_KEY="secret", TABLE_NAME="ContactMessages", AWS_DEFAULT_REGION="ap-south-1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


try:
    import boto3  # noqa: F401
    from botocore.exceptions import ClientError  # noqa: F401
except ImportError:  # allow running without boto3 installed (tests use fakes anyway)
    import types
    b, bc, bce = types.ModuleType("boto3"), types.ModuleType("botocore"), types.ModuleType("botocore.exceptions")
    class ClientError(Exception):
        def __init__(self, response, op): self.response = response
    bce.ClientError = ClientError
    b.resource = b.client = lambda *a, **k: None
    bc.exceptions = bce
    sys.modules.update({"boto3": b, "botocore": bc, "botocore.exceptions": bce})


class FakeTable:
    def __init__(self): self.items = {}
    def put_item(self, Item): self.items[Item["id"]] = Item
    def scan(self, **kw): return {"Items": list(self.items.values())}
    def get_item(self, Key): return {"Item": self.items[Key["id"]]} if Key["id"] in self.items else {}
    def update_item(self, **kw):
        from botocore.exceptions import ClientError
        i = kw["Key"]["id"]
        if i not in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        v = kw["ExpressionAttributeValues"]
        if ":s" in v: self.items[i]["status"] = v[":s"]
        if ":n" in v: self.items[i]["adminNote"] = v[":n"]
        return {"Attributes": self.items[i]}
    def delete_item(self, Key, **kw):
        from botocore.exceptions import ClientError
        if Key["id"] not in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "DeleteItem")
        del self.items[Key["id"]]


class FakeComprehend:
    def detect_dominant_language(self, Text): return {"Languages": [{"LanguageCode": "en"}]}
    def detect_sentiment(self, Text, LanguageCode):
        neg = "terrible" in Text or "crash" in Text
        return {"Sentiment": "NEGATIVE" if neg else "POSITIVE",
                "SentimentScore": {"Positive": 0.1, "Negative": 0.8, "Neutral": 0.05, "Mixed": 0.05}}
    def detect_key_phrases(self, Text, LanguageCode):
        return {"KeyPhrases": [{"Text": "the app", "Score": 0.99}, {"Text": "The App", "Score": 0.9}]}


GEMINI_OK = ('Sure: {"summary": "App crashes repeatedly.", "reply": "Hi Asha, sorry about the crashes.", '
             '"sentiment": "NEGATIVE", "keyPhrases": ["crashes"]}')


table = FakeTable()
with mock.patch("boto3.resource") as res, mock.patch("boto3.client") as cli:
    res.return_value.Table.return_value = table
    cli.return_value = FakeComprehend()
    import lambda_function as lf


def ev(route, body=None, key=None, id=None):
    e = {"routeKey": route, "headers": {"X-Admin-Key": key} if key else {},
         "body": json.dumps(body) if body is not None else None}
    if id: e["pathParameters"] = {"id": id}
    return e


def call(*a, **k):
    r = lf.lambda_handler(ev(*a, **k), None)
    return r["statusCode"], json.loads(r["body"])


class Tests(unittest.TestCase):
    def setUp(self):
        table.items.clear()
        p = mock.patch.object(lf, "call_gemini", return_value=(GEMINI_OK, "test-model"))
        self.gemini = p.start()
        self.addCleanup(p.stop)

    def test_full_crud(self):
        code, b = call("POST /contact", {"name": "Asha", "email": "a@b.com", "message": "The app keeps crashing, terrible"})
        self.assertEqual(code, 200); self.assertTrue(b["success"])
        self.assertEqual(b["sentiment"], "NEGATIVE"); self.assertEqual(b["category"], "Bug Report")
        mid = b["id"]
        self.assertEqual(table.items[mid]["priority"], "High")
        self.assertEqual(table.items[mid]["keyPhrases"], ["the app"])  # de-duplicated
        self.assertEqual(table.items[mid]["aiSummary"], "App crashes repeatedly.")
        self.assertIn("sorry", table.items[mid]["aiSuggestedReply"])

        self.assertEqual(call("GET /messages")[0], 401)
        self.assertEqual(call("GET /messages", key="wrong")[0], 401)
        code, b = call("GET /messages", key="secret"); self.assertEqual(b["count"], 1)
        self.assertEqual(call("GET /messages/{id}", key="secret", id=mid)[0], 200)
        self.assertEqual(call("GET /messages/{id}", key="secret", id="nope")[0], 404)

        code, b = call("PUT /messages/{id}", {"status": "Resolved"}, key="secret", id=mid)
        self.assertEqual(b["item"]["status"], "Resolved")
        self.assertEqual(call("PUT /messages/{id}", {"status": "Bogus"}, key="secret", id=mid)[0], 400)
        self.assertEqual(call("PUT /messages/{id}", {}, key="secret", id=mid)[0], 400)
        self.assertEqual(call("PUT /messages/{id}", {"status": "New"}, key="secret", id="nope")[0], 404)

        self.assertEqual(call("DELETE /messages/{id}", key="secret", id=mid)[0], 200)
        self.assertEqual(call("DELETE /messages/{id}", key="secret", id=mid)[0], 404)

    def test_validation(self):
        self.assertEqual(call("POST /contact", {"name": "", "email": "a@b.com", "message": "x"})[0], 400)
        self.assertEqual(call("POST /contact", {"name": "A", "email": "bad", "message": "x"})[0], 400)
        self.assertEqual(call("POST /contact", {"name": "A", "email": "a@b.com", "message": "x" * 2001})[0], 400)
        r = lf.lambda_handler({"routeKey": "POST /contact", "body": "not json"}, None)
        self.assertEqual(r["statusCode"], 400)

    def test_ai_failure_still_saves(self):
        self.gemini.side_effect = RuntimeError("down")
        with mock.patch.object(lf, "comprehend") as c:
            c.detect_dominant_language.side_effect = RuntimeError("AccessDenied")
            code, b = call("POST /contact", {"name": "A", "email": "a@b.com", "message": "How do I reset?"})
        self.assertEqual(code, 200); self.assertEqual(b["sentiment"], "UNANALYZED"); self.assertEqual(b["category"], "Question")

    def test_gemini_prompt_wraps_message(self):
        call("POST /contact", {"name": "A", "email": "a@b.com", "message": "Hello there"})
        self.assertIn("<message>", self.gemini.call_args[0][1])

    def test_gemini_failure_still_saves(self):
        self.gemini.side_effect = RuntimeError("Gemini HTTP 429")
        code, body = call("POST /contact", {"name": "A", "email": "a@b.com", "message": "Great job"})
        self.assertEqual(code, 200)
        self.assertNotIn("aiSummary", table.items[body["id"]])
        self.assertEqual(table.items[body["id"]]["sentiment"], "POSITIVE")

    def test_gemini_garbage_output_still_saves(self):
        self.gemini.return_value = ("no json here", "test-model")
        code, body = call("POST /contact", {"name": "A", "email": "a@b.com", "message": "Great job"})
        self.assertEqual(code, 200)
        self.assertNotIn("aiSummary", table.items[body["id"]])

    def test_genai_off_or_no_key(self):
        with mock.patch.object(lf, "GEMINI_API_KEY", ""):
            code, body = call("POST /contact", {"name": "A", "email": "a@b.com", "message": "Great job"})
        self.assertEqual(code, 200)
        self.assertNotIn("aiSummary", table.items[body["id"]])
        self.gemini.assert_not_called()

    def test_comprehend_unavailable_falls_back_to_gemini(self):
        with mock.patch.object(lf, "comprehend") as c:
            c.detect_dominant_language.side_effect = RuntimeError("SubscriptionRequiredException")
            code, body = call("POST /contact", {"name": "Asha", "email": "a@b.com", "message": "The app keeps crashing"})
        item = table.items[body["id"]]
        self.assertEqual(code, 200)
        self.assertEqual(body["sentiment"], "NEGATIVE")
        self.assertEqual(item["sentimentSource"], "gemini")
        self.assertEqual(item["priority"], "High")
        self.assertEqual(item["keyPhrases"], ["crashes"])
        self.assertNotIn("_sentiment", item)

    def test_comprehend_and_gemini_both_down_still_saves(self):
        self.gemini.side_effect = RuntimeError("down")
        with mock.patch.object(lf, "comprehend") as c:
            c.detect_dominant_language.side_effect = RuntimeError("down")
            code, body = call("POST /contact", {"name": "A", "email": "a@b.com", "message": "hello"})
        self.assertEqual(code, 200)
        self.assertEqual(table.items[body["id"]]["sentiment"], "UNANALYZED")

    def test_unknown_route(self):
        self.assertEqual(call("PATCH /x")[0], 404)



class GeminiModelFallback(unittest.TestCase):
    """call_gemini tries the next model name when one returns 404."""
    def test_404_then_success(self):
        import io, urllib.error
        calls = []

        def fake(model, body):
            calls.append(model)
            if model == "bad-model":
                raise urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b'{"error":"not found"}'))
            return "OK-TEXT"

        with mock.patch.object(lf, "GEMINI_MODEL", "bad-model"), \
             mock.patch.object(lf, "_working_model", None), \
             mock.patch.object(lf, "_gemini_request", side_effect=fake):
            text, used = lf.call_gemini("s", "p")
        self.assertEqual(text, "OK-TEXT")
        self.assertEqual(calls, ["bad-model", "gemini-flash-lite-latest"])
        self.assertEqual(used, "gemini-flash-lite-latest")

    def test_non_404_stops(self):
        import io, urllib.error
        def fake(model, body):
            raise urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(b"bad key"))
        with mock.patch.object(lf, "_working_model", None), mock.patch.object(lf, "_gemini_request", side_effect=fake) as m:
            with self.assertRaises(RuntimeError):
                lf.call_gemini("s", "p")
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
