# BUILDLOG.md — AI Usage & Engineering Decisions

**Student:** Deepak R  
**Project:** Embeddable Widget & Lead-Capture Platform  
**Program:** FlyRank Backend Internship Capstone  

---

## 1. Overview of AI Partnership

During this capstone build, Claude 3.7 / 3.5 Sonnet and Gemini were used as an architectural sounding board, code generator, and edge-case antagonist following the **4D AI Fluency Framework** (Delegation, Description, Discernment, Diligence).

All architectural decisions, error boundaries, security safeguards, and manual code reviews were owned by me.

---

## 2. Where AI Helped Most

1. **Boilerplate Pydantic & SQLAlchemy Models:**
   - AI rapidly drafted the initial column definitions, foreign key relationships, and Pydantic schemas.
   - Saved approximately 2 hours of repetitive syntax typing.

2. **CORS & Preflight Options Header Strategy:**
   - Discussed browser preflight mechanics and confirmed which headers must be exposed (`ETag`, `Cache-Control`, `X-RateLimit-Remaining`) to allow clean client-side widget operations.

3. **Exhaustive Edge-Case Test Scenarios:**
   - Prompted AI to act as a black-hat penetration tester to identify vectors for payload flooding and honeypot circumvention.

---

## 3. Where AI Was Wrong or Hallucinated (And What I Fixed)

### Error 1: The Side-Effect Cancellation Bug
* **What AI generated:** The AI initially placed the email notification inside the main database transaction block:
  ```python
  # AI's flawed initial proposal
  with db.begin():
      db.add(submission)
      send_email(submission.email) # If SMTP times out, transaction rolls back!
  ```
* **Why it failed:** If the third-party email provider or SMTP socket threw a timeout error, SQLAlchemy rolled back the transaction, dropping the valid submission!
* **My fix:** Decoupled the email trigger completely outside the database commit, wrapped it inside a dedicated `try...except` boundary in `services.py`, and logged failures without propagating exceptions to the client.

### Error 2: The 204 No Content Body Violation
* **What AI generated:** For the `DELETE /admin/widgets/{id}` endpoint, AI returned:
  ```python
  return {"message": "Widget deleted successfully"} # HTTP 204 with JSON body!
  ```
* **Why it failed:** RFC 9110 strictly mandates that a `204 No Content` response must NEVER have an entity body. Some HTTP proxy servers and clients throw protocol violations when a body is attached.
* **My fix:** Used `Response(status_code=status.HTTP_204_NO_CONTENT)` with an empty body.

### Error 3: Honeypot Client-Side Visibility
* **What AI generated:** AI added `<input type="hidden" name="_hp_trap">` to the form.
* **Why it failed:** Modern spam bots specifically inspect the DOM for `type="hidden"` and intentionally skip them. A proper honeypot must look like a normal text input (`type="text"`) that is hidden visually from humans using off-screen CSS (`position: absolute; left: -9999px;`).
* **My fix:** Changed the input to `type="text"` with an accessible off-screen container.

---

## 4. Explaining Key Code Lines (Evaluator Spot-Check Prep)

If asked by an evaluator to explain specific lines:

* **Sliding Window Rate Limiter (`services.py:22-38`):**
  > *"I implemented an in-memory sliding window using `time.time()`. Instead of fixed-window counters that suffer from burst exploitation at window boundaries, this dynamically filters timestamps where `t > now - window_seconds`. It guarantees that no more than 5 requests can occur within any rolling 10-second slice."*

* **Geo Fallback Chain (`services.py:98-112`):**
  > *"This embodies graceful degradation. We query Provider A (ip-api.com). If it times out or returns non-200, execution falls through to Provider B (ipapi.co). If both fail, the method returns `(None, None, None)`. The caller stores the submission row with null geo columns rather than raising an HTTP 500 error."*

* **Tenant Isolation in ORM Query (`main.py:194-201`):**
  > *"We never rely on the frontend passing a tenant ID in the URL. Instead, the `get_current_tenant` dependency extracts the `X-API-Key` header and looks up the authenticated tenant. Every query filters with `Widget.tenant_id == tenant.id`, making it mathematically impossible for Tenant A to query or mutate Tenant B's data."*
