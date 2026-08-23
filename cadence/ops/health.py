"""
Self-Awareness Module

Provides self-monitoring and adaptive learning capabilities for the bot.
Tracks performance metrics, detects degradation, and enables model adaptation.
"""

import sys
import time
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum
import statistics


class HealthStatus(Enum):
    """Bot health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class PerformanceMetrics:
    """Performance metrics snapshot."""
    timestamp: datetime
    inference_time_ms: float
    memory_usage_mb: float
    cpu_percent: float
    predictions_per_minute: float
    error_rate: float
    model_accuracy_estimate: float


@dataclass
class Alert:
    """System alert."""
    timestamp: datetime
    level: str  # info, warning, error, critical
    component: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)


class SelfAwarenessModule:
    """
    Self-monitoring and adaptive learning for the bot.
    
    Features:
    - Performance tracking (latency, throughput, errors)
    - Health monitoring with automatic degradation detection
    - Drift detection for model performance
    - Alert generation
    - Periodic self-diagnostics
    """
    
    def __init__(
        self,
        metrics_window_size: int = 100,
        health_check_interval_seconds: int = 30,
        alert_callback: Optional[Callable[[Alert], None]] = None
    ):
        """
        Initialize self-awareness module.
        
        Parameters
        ----------
        metrics_window_size : int
            Number of metrics to keep in rolling window
        health_check_interval_seconds : int
            Interval between health checks
        alert_callback : Callable
            Callback for alerts
        """
        self.metrics_window_size = metrics_window_size
        self.health_check_interval = health_check_interval_seconds
        self.alert_callback = alert_callback
        
        # Metrics storage
        self._inference_times: deque = deque(maxlen=metrics_window_size)
        self._prediction_counts: deque = deque(maxlen=metrics_window_size)
        self._error_counts: deque = deque(maxlen=metrics_window_size)
        self._model_confidences: Dict[str, deque] = {}
        
        # Alerts
        self._alerts: deque = deque(maxlen=1000)
        
        # Health status
        self._health_status = HealthStatus.UNKNOWN
        self._last_health_check: Optional[datetime] = None
        
        # Thresholds
        self.thresholds = {
            'max_inference_time_ms': 500,
            'min_predictions_per_minute': 10,
            'max_error_rate': 0.1,
            'min_average_confidence': 0.3,
            'confidence_drop_threshold': 0.2
        }
        
        # Monitoring thread
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        # State tracking
        self._start_time = datetime.now()
        self._total_predictions = 0
        self._total_errors = 0
    
    def record_inference(
        self,
        model_name: str,
        inference_time_ms: float,
        confidence: float,
        success: bool = True
    ):
        """
        Record an inference result.
        
        Parameters
        ----------
        model_name : str
            Name of the model
        inference_time_ms : float
            Time taken for inference
        confidence : float
            Prediction confidence
        success : bool
            Whether inference succeeded
        """
        self._inference_times.append(inference_time_ms)
        
        if model_name not in self._model_confidences:
            self._model_confidences[model_name] = deque(maxlen=self.metrics_window_size)
        self._model_confidences[model_name].append(confidence)
        
        self._total_predictions += 1
        
        if not success:
            self._total_errors += 1
            self._error_counts.append(1)
        else:
            self._error_counts.append(0)
    
    def record_prediction_batch(self, batch_size: int, total_time_ms: float):
        """Record a batch of predictions."""
        self._prediction_counts.append(batch_size)
        self._inference_times.append(total_time_ms / max(1, batch_size))
    
    def get_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics."""
        now = datetime.now()
        uptime = (now - self._start_time).total_seconds()
        
        # Calculate metrics
        avg_inference = statistics.mean(self._inference_times) if self._inference_times else 0
        
        # Predictions per minute
        ppm = (self._total_predictions / max(1, uptime)) * 60
        
        # Error rate
        error_rate = self._total_errors / max(1, self._total_predictions)
        
        # Average confidence across all models
        all_confidences = []
        for confs in self._model_confidences.values():
            all_confidences.extend(list(confs))
        avg_confidence = statistics.mean(all_confidences) if all_confidences else 0
        
        return PerformanceMetrics(
            timestamp=now,
            inference_time_ms=avg_inference,
            memory_usage_mb=self._get_memory_usage(),
            cpu_percent=self._get_cpu_percent(),
            predictions_per_minute=ppm,
            error_rate=error_rate,
            model_accuracy_estimate=avg_confidence
        )
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            return 0.0
    
    def _get_cpu_percent(self) -> float:
        """Get current CPU percentage."""
        try:
            import psutil
            return psutil.cpu_percent(interval=0.1)
        except ImportError:
            return 0.0
    
    def check_health(self) -> HealthStatus:
        """Perform health check and return status."""
        metrics = self.get_metrics()
        issues = []
        
        # Check inference time
        if metrics.inference_time_ms > self.thresholds['max_inference_time_ms']:
            issues.append(f"High inference time: {metrics.inference_time_ms:.1f}ms")
        
        # Check error rate
        if metrics.error_rate > self.thresholds['max_error_rate']:
            issues.append(f"High error rate: {metrics.error_rate:.1%}")
        
        # Check throughput
        if self._total_predictions > 10:  # After warm-up
            if metrics.predictions_per_minute < self.thresholds['min_predictions_per_minute']:
                issues.append(f"Low throughput: {metrics.predictions_per_minute:.1f} pred/min")
        
        # Check model confidence drift
        for model, confs in self._model_confidences.items():
            if len(confs) >= 20:
                recent = list(confs)[-10:]
                older = list(confs)[-20:-10]
                recent_avg = statistics.mean(recent)
                older_avg = statistics.mean(older)
                
                if older_avg - recent_avg > self.thresholds['confidence_drop_threshold']:
                    issues.append(f"Confidence drop in {model}: {older_avg:.2f} -> {recent_avg:.2f}")
        
        # Determine status
        if len(issues) == 0:
            self._health_status = HealthStatus.HEALTHY
        elif len(issues) <= 2:
            self._health_status = HealthStatus.DEGRADED
            self._create_alert("warning", "health", f"System degraded: {'; '.join(issues)}")
        else:
            self._health_status = HealthStatus.CRITICAL
            self._create_alert("critical", "health", f"System critical: {'; '.join(issues)}")
        
        self._last_health_check = datetime.now()
        return self._health_status
    
    def _create_alert(self, level: str, component: str, message: str, context: Dict = None):
        """Create and store an alert."""
        alert = Alert(
            timestamp=datetime.now(),
            level=level,
            component=component,
            message=message,
            context=context or {}
        )
        self._alerts.append(alert)
        
        if self.alert_callback:
            try:
                self.alert_callback(alert)
            except Exception:
                pass
    
    def get_alerts(self, since: datetime = None, level: str = None) -> List[Alert]:
        """Get alerts, optionally filtered."""
        alerts = list(self._alerts)
        
        if since:
            alerts = [a for a in alerts if a.timestamp >= since]
        if level:
            alerts = [a for a in alerts if a.level == level]
        
        return alerts
    
    def get_model_stats(self, model_name: str) -> Dict[str, Any]:
        """Get statistics for a specific model."""
        if model_name not in self._model_confidences:
            return {}
        
        confs = list(self._model_confidences[model_name])
        if not confs:
            return {}
        
        return {
            'sample_count': len(confs),
            'avg_confidence': statistics.mean(confs),
            'min_confidence': min(confs),
            'max_confidence': max(confs),
            'std_confidence': statistics.stdev(confs) if len(confs) > 1 else 0
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get overall system summary."""
        metrics = self.get_metrics()
        
        return {
            'health_status': self._health_status.value,
            'uptime_seconds': (datetime.now() - self._start_time).total_seconds(),
            'total_predictions': self._total_predictions,
            'total_errors': self._total_errors,
            'metrics': {
                'avg_inference_time_ms': metrics.inference_time_ms,
                'predictions_per_minute': metrics.predictions_per_minute,
                'error_rate': metrics.error_rate,
                'memory_mb': metrics.memory_usage_mb,
                'cpu_percent': metrics.cpu_percent
            },
            'models': {
                name: self.get_model_stats(name) 
                for name in self._model_confidences.keys()
            },
            'recent_alerts': len([a for a in self._alerts if a.timestamp > datetime.now() - timedelta(hours=1)])
        }
    
    def _monitor_loop(self):
        """Background monitoring loop."""
        while self._running:
            self.check_health()
            time.sleep(self.health_check_interval)
    
    def start_monitoring(self):
        """Start background monitoring."""
        if self._running:
            return
        
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop background monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
    
    @property
    def health_status(self) -> HealthStatus:
        return self._health_status


# Singleton instance
_self_awareness: Optional[SelfAwarenessModule] = None


def get_self_awareness() -> SelfAwarenessModule:
    """Get or create the default self-awareness module."""
    global _self_awareness
    if _self_awareness is None:
        _self_awareness = SelfAwarenessModule()
    return _self_awareness


if __name__ == "__main__":
    print("Self-Awareness Module Demo")
    print("=" * 50)
    
    # Create module
    awareness = SelfAwarenessModule(
        alert_callback=lambda a: print(f"ALERT [{a.level}]: {a.message}")
    )
    
    # Simulate some inferences
    import random
    for i in range(50):
        awareness.record_inference(
            model_name=random.choice(["ctu13", "keystroke", "beth"]),
            inference_time_ms=random.uniform(10, 100),
            confidence=random.uniform(0.5, 1.0),
            success=random.random() > 0.05
        )
    
    # Check health
    status = awareness.check_health()
    print(f"Health Status: {status.value}")
    
    # Get summary
    summary = awareness.get_summary()
    print(f"\nSummary:")
    print(json.dumps(summary, indent=2, default=str))
