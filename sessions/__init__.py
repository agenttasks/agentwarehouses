"""Session infrastructure for research document fetching and note-taking.

Provides deterministic session IDs, auto-populated device/surface metadata,
page fetch templates, scratchpad, and blog post formatting — modeled on
tooling used by Anthropic alignment engineers (safety-research repos).

Usage:
    from sessions import SessionManager
    mgr = SessionManager()
    sid = mgr.create_session(topic="transformer-circuits-pub")
    mgr.add_page(sid, url="https://transformer-circuits.pub/...", content="...")
    mgr.write_scratchpad(sid, "Key finding: ...")
    mgr.write_blog_post(sid, title="...", body="...")
"""
