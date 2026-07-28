import pytest

from app.services.upload_gate import UploadGate


@pytest.mark.asyncio
async def test_upload_gate_rejects_excess_work_without_waiting() -> None:
    gate = UploadGate(capacity=1)

    assert await gate.try_acquire() is True
    assert await gate.try_acquire() is False

    await gate.release()
    assert await gate.try_acquire() is True
    await gate.release()


@pytest.mark.asyncio
async def test_upload_gate_does_not_allow_extra_release() -> None:
    gate = UploadGate(capacity=1)

    with pytest.raises(RuntimeError):
        await gate.release()
