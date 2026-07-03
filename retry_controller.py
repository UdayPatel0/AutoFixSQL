"""
retry_controller.py — Wraps the execute -> diagnose -> repair loop with
a bounded retry limit. On repeated failure, or once no repair rule
applies, returns a safe-failure result with a clear error message
instead of looping forever or returning a misleading result.
"""

from dataclasses import dataclass, field
from typing import Optional

from src.config import MAX_RETRIES
from src.execution_monitor import run_query, ExecutionResult
from src.error_diagnosis import diagnose, Diagnosis
from src.repair_engine import repair, RepairError


@dataclass
class RepairAttempt:
    attempt_number: int
    sql_tried: str
    result: ExecutionResult
    diagnosis: Optional[Diagnosis] = None
    repaired_sql: Optional[str] = None


@dataclass
class PipelineResult:
    success: bool
    final_sql: str
    result: Optional[ExecutionResult]
    attempts: list = field(default_factory=list)
    safe_failure_message: Optional[str] = None


def run_with_repair(
    sql: str,
    schema: dict,
    conn=None,
    max_retries: int = MAX_RETRIES,
) -> PipelineResult:
    """
    Execute `sql`. If it fails, diagnose + repair + retry, up to
    `max_retries` times. Returns a PipelineResult with the full
    attempt history for transparency/logging.
    """
    attempts = []
    current_sql = sql

    for attempt_num in range(1, max_retries + 2):  # initial try + max_retries repairs
        result = run_query(current_sql, conn=conn)
        attempt = RepairAttempt(attempt_number=attempt_num, sql_tried=current_sql, result=result)
        attempts.append(attempt)

        if result.success:
            return PipelineResult(
                success=True, final_sql=current_sql, result=result, attempts=attempts
            )

        if attempt_num > max_retries:
            break

        try:
            diag = diagnose(result, schema)
            attempt.diagnosis = diag
            repaired_sql = repair(current_sql, diag, schema)
            attempt.repaired_sql = repaired_sql
            current_sql = repaired_sql
        except RepairError as e:
            return PipelineResult(
                success=False,
                final_sql=current_sql,
                result=result,
                attempts=attempts,
                safe_failure_message=(
                    f"AutoFixSQL could not safely repair this query after "
                    f"{attempt_num} attempt(s). Last error: {result.error_message}. "
                    f"Reason repair stopped: {e}"
                ),
            )

    # Exhausted retries
    last = attempts[-1]
    return PipelineResult(
        success=False,
        final_sql=current_sql,
        result=last.result,
        attempts=attempts,
        safe_failure_message=(
            f"AutoFixSQL reached the max retry limit ({max_retries}) without a "
            f"successful execution. Last error: {last.result.error_message}"
        ),
    )
