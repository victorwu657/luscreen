use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, mpsc, Mutex,
};
use std::thread;
use std::time::Duration;

mod capturer;
mod processor;
mod gpu_processor;
use capturer::MouseData;
use processor::ParallelProcessor;
use gpu_processor::GpuProcessor;

/// A Python class for screen recording.
#[pyclass]
struct ScreenRecorder {
    stop_signal: Arc<AtomicBool>,
    pause_signal: Arc<AtomicBool>,
    handle: Option<thread::JoinHandle<()>>,
    rx: Option<mpsc::Receiver<()>>,
    mouse_storage: Arc<Mutex<Vec<MouseData>>>,
}

#[pymethods]
impl ScreenRecorder {
    #[new]
    fn new() -> Self {
        ScreenRecorder {
            stop_signal: Arc::new(AtomicBool::new(false)),
            pause_signal: Arc::new(AtomicBool::new(false)),
            handle: None,
            rx: None,
            mouse_storage: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Starts recording to the specified file.
    /// This method spawns a new thread and returns immediately.
    fn start(&mut self, filename: String) -> PyResult<()> {
        if self.handle.is_some() {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "Recording is already in progress",
            ));
        }

        // Reset signals and mouse storage
        self.stop_signal.store(false, Ordering::Relaxed);
        self.pause_signal.store(false, Ordering::Relaxed);
        if let Ok(mut storage) = self.mouse_storage.lock() {
            storage.clear();
        }
        
        let stop_signal = self.stop_signal.clone();
        let mouse_storage = self.mouse_storage.clone();
        let filename_clone = filename.clone();
        let (tx, rx) = mpsc::channel();

        // Spawn a thread to run the capture loop
        // We use a thread because windows-capture blocks the current thread
        let handle = thread::spawn(move || {
            if let Err(e) = capturer::start_capture(filename_clone, stop_signal, mouse_storage) {
                log::error!("Capture failed: {}", e);
            }
            let _ = tx.send(());
        });

        self.handle = Some(handle);
        self.rx = Some(rx);
        Ok(())
    }

    fn pause(&mut self) {
        self.pause_signal.store(true, Ordering::Relaxed);
    }

    fn resume(&mut self) {
        self.pause_signal.store(false, Ordering::Relaxed);
    }

    /// Stops the recording and returns the mouse metadata.
    fn stop(&mut self, py: Python<'_>) -> PyResult<PyObject> {
        if let Some(handle) = self.handle.take() {
            // Signal the capture thread to stop
            self.stop_signal.store(true, Ordering::Relaxed);
            
            // Wait for completion with timeout
            if let Some(rx) = self.rx.take() {
                match rx.recv_timeout(Duration::from_secs(5)) {
                    Ok(_) => {
                         // Thread finished successfully
                         if let Err(_) = handle.join() {
                            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                                "Failed to join capture thread",
                            ));
                        }
                    },
                    Err(_) => {
                        // Timeout or disconnect
                        log::error!("Timeout waiting for capture thread to stop.");
                         return Err(PyErr::new::<pyo3::exceptions::PyTimeoutError, _>(
                            "Timeout waiting for capture thread to stop. Recording may be incomplete.",
                        ));
                    }
                }
            } else {
                 // No rx channel? Fallback to join
                 if let Err(_) = handle.join() {
                    return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        "Failed to join capture thread",
                    ));
                }
            }
        }
        // Collect mouse data
        let mut py_data = Vec::new();
        if let Ok(storage) = self.mouse_storage.lock() {
            for data in storage.iter() {
                let dict = PyDict::new_bound(py);
                dict.set_item("t", data.t)?;
                dict.set_item("x", data.x)?;
                dict.set_item("y", data.y)?;
                dict.set_item("click", data.click)?;
                py_data.push(dict);
            }
        }
        
        let py_list = PyList::new_bound(py, py_data);
        Ok(py_list.into())
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn rust_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ScreenRecorder>()?;
    m.add_class::<ParallelProcessor>()?;
    m.add_class::<GpuProcessor>()?;
    Ok(())
}