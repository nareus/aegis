"""CRUD for interview_sessions table."""

from uuid import UUID

from aegis.db.engine import get_pool


class InterviewRepository:
    """Persistence for mock interview sessions."""

    async def create_session(
        self,
        *,
        session_type: str,
        question: str,
        job_id: UUID | None = None,
        company: str | None = None,
    ) -> UUID:
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO interview_sessions (job_id, company, session_type, question)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            job_id,
            company,
            session_type,
            question,
        )
        return row["id"]

    async def save_answer(
        self,
        session_id: UUID,
        *,
        answer: str,
        feedback: str,
        score: float,
        weak_areas: list[str],
    ) -> None:
        pool = await get_pool()
        await pool.execute(
            """
            UPDATE interview_sessions
            SET answer = $1, feedback = $2, score = $3, weak_areas = $4,
                answered_at = NOW()
            WHERE id = $5
            """,
            answer,
            feedback,
            score,
            weak_areas,
            session_id,
        )

    async def get_session(self, session_id: UUID) -> dict | None:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM interview_sessions WHERE id = $1", session_id
        )
        return dict(row) if row else None

    async def list_sessions(
        self,
        *,
        job_id: UUID | None = None,
        company: str | None = None,
        session_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        pool = await get_pool()
        clauses = []
        params: list = []
        idx = 1

        if job_id is not None:
            clauses.append(f"job_id = ${idx}")
            params.append(job_id)
            idx += 1
        if company is not None:
            clauses.append(f"company ILIKE ${idx}")
            params.append(f"%{company}%")
            idx += 1
        if session_type is not None:
            clauses.append(f"session_type = ${idx}")
            params.append(session_type)
            idx += 1

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = await pool.fetch(
            f"SELECT * FROM interview_sessions {where} ORDER BY created_at DESC LIMIT ${idx}",
            *params,
        )
        return [dict(r) for r in rows]

    async def get_readiness(self, company: str | None = None) -> dict:
        """Return average score and session counts, optionally filtered by company."""
        pool = await get_pool()
        where = "WHERE company ILIKE $1" if company else ""
        params = [f"%{company}%"] if company else []

        rows = await pool.fetch(
            f"""
            SELECT session_type,
                   COUNT(*)                                AS total,
                   COUNT(*) FILTER (WHERE score IS NOT NULL) AS evaluated,
                   AVG(score) FILTER (WHERE score IS NOT NULL) AS avg_score
            FROM interview_sessions
            {where}
            GROUP BY session_type
            """,
            *params,
        )

        breakdown: dict[str, dict] = {}
        overall_scores = []
        for row in rows:
            breakdown[row["session_type"]] = {
                "total": row["total"],
                "evaluated": row["evaluated"],
                "avg_score": round(row["avg_score"] or 0.0, 2),
            }
            if row["avg_score"] is not None:
                overall_scores.append(row["avg_score"])

        overall = round(sum(overall_scores) / len(overall_scores), 2) if overall_scores else None

        # Collect most common weak areas across sessions
        weak_rows = await pool.fetch(
            f"""
            SELECT unnest(weak_areas) AS area, COUNT(*) AS cnt
            FROM interview_sessions
            {where}
            WHERE weak_areas IS NOT NULL AND array_length(weak_areas, 1) > 0
            GROUP BY area
            ORDER BY cnt DESC
            LIMIT 10
            """,
            *params,
        )
        top_weak = [r["area"] for r in weak_rows]

        return {
            "company": company,
            "overall_score": overall,
            "breakdown": breakdown,
            "top_weak_areas": top_weak,
        }
