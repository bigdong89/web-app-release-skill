// Fixture build artifact — all credentials below are fake examples, not real secrets.
const AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE";

async function callApi() {
  const res = await fetch("/api", {
    headers: { Authorization: "Bearer sk-live-fakekey0123456789abcdef" },
  });
  return res.json();
}

callApi();
