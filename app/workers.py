"""Small signal-based jobs; results are delivered on the receiver's Qt thread."""
import logging
from PySide6.QtCore import QObject, Signal, QRunnable


class JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()

    def run(self):
        try:
            self.signals.done.emit(self.function())
        except Exception as error:
            logging.getLogger("textspeak.jobs").exception("Background operation failed")
            self.signals.failed.emit(str(error))
