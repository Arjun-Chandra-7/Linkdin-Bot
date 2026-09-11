from app.api.v1.profile import profile_guidance
from app.core.settings_store import set_setting


def test_profile_guidance_uses_stored_identity_without_overclaiming(db):
    set_setting(db, "linkedin_display_name", "Arjun Chandra")
    set_setting(db, "linkedin_headline", "AI Engineer · Agentic Systems")
    db.flush()

    guidance = profile_guidance(db=db, _=None)

    assert guidance.suggested_headline == "AI Engineer · Agentic Systems"
    assert guidance.suggested_about.startswith("I am Arjun Chandra.")
    assert "Publish a few posts before rewriting your profile" in guidance.recommendations[0]
