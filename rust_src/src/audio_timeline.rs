use hound::{SampleFormat, WavReader, WavWriter};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

#[pyclass]
pub struct AudioTimelineBuilder;

fn ms_to_samples(ms: u64, sample_rate: u32) -> usize {
    (((ms as u128) * (sample_rate as u128) + 500) / 1000) as usize
}

fn build_wav_timeline_from_samples_impl(
    source_audio_path: &str,
    output_wav_path: &str,
    segments_samples: &[(u64, u64)],
) -> Result<(usize, usize, u32, u16), String> {
    if segments_samples.is_empty() {
        return Err("segments_samples 不能为空".to_string());
    }

    let mut reader =
        WavReader::open(source_audio_path).map_err(|e| format!("打开源 WAV 失败: {e}"))?;
    let spec = reader.spec();

    if spec.channels != 1 {
        return Err(format!("仅支持单声道 WAV，当前 channels={}", spec.channels));
    }
    if spec.bits_per_sample != 16 {
        return Err(format!(
            "仅支持 16-bit PCM WAV，当前 bits_per_sample={}",
            spec.bits_per_sample
        ));
    }
    if spec.sample_format != SampleFormat::Int {
        return Err("仅支持整型 PCM WAV".to_string());
    }

    let source_samples: Vec<i16> = reader
        .samples::<i16>()
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("读取 WAV 样本失败: {e}"))?;

    let sample_rate = spec.sample_rate;
    let mut total_output_samples: usize = 0;
    for (start_sample, end_sample) in segments_samples.iter().copied() {
        if end_sample < start_sample {
            return Err(format!(
                "发现非法片段范围: start_sample={start_sample}, end_sample={end_sample}"
            ));
        }
        total_output_samples += (end_sample - start_sample) as usize;
    }

    let mut merged_samples = Vec::<i16>::with_capacity(total_output_samples);
    let mut silence_segments = 0usize;

    for (start_sample, end_sample) in segments_samples.iter().copied() {
        let start_idx = start_sample as usize;
        let expected_len = (end_sample - start_sample) as usize;
        let available_len = if start_idx < source_samples.len() {
            expected_len.min(source_samples.len().saturating_sub(start_idx))
        } else {
            0
        };

        if available_len > 0 {
            merged_samples.extend_from_slice(
                &source_samples[start_idx..start_idx.saturating_add(available_len)],
            );
        }

        if available_len < expected_len {
            merged_samples.resize(merged_samples.len() + (expected_len - available_len), 0);
            silence_segments += 1;
        }
    }

    let mut writer =
        WavWriter::create(output_wav_path, spec).map_err(|e| format!("创建输出 WAV 失败: {e}"))?;
    for sample in merged_samples.iter().copied() {
        writer
            .write_sample(sample)
            .map_err(|e| format!("写入输出 WAV 失败: {e}"))?;
    }
    writer
        .finalize()
        .map_err(|e| format!("完成输出 WAV 失败: {e}"))?;

    Ok((segments_samples.len(), silence_segments, sample_rate, spec.channels))
}

#[pymethods]
impl AudioTimelineBuilder {
    #[staticmethod]
    #[pyo3(signature = (source_audio_path, output_wav_path, segments_ms))]
    pub fn build_wav_timeline(
        py: Python<'_>,
        source_audio_path: String,
        output_wav_path: String,
        segments_ms: Vec<(u64, u64)>,
    ) -> PyResult<(usize, usize, u32, u16)> {
        let mut segments_samples = Vec::with_capacity(segments_ms.len());
        let sample_rate = {
            let reader = WavReader::open(&source_audio_path)
                .map_err(|e| PyRuntimeError::new_err(format!("打开源 WAV 失败: {e}")))?;
            reader.spec().sample_rate
        };
        for (start_ms, end_ms) in segments_ms.iter().copied() {
            if end_ms < start_ms {
                return Err(PyValueError::new_err(format!(
                    "发现非法片段范围: start_ms={start_ms}, end_ms={end_ms}"
                )));
            }
            segments_samples.push((
                ms_to_samples(start_ms, sample_rate) as u64,
                ms_to_samples(end_ms, sample_rate) as u64,
            ));
        }
        py.allow_threads(|| {
            build_wav_timeline_from_samples_impl(
                &source_audio_path,
                &output_wav_path,
                &segments_samples,
            )
        })
        .map_err(|msg| {
            if msg.contains("仅支持") || msg.contains("非法片段") || msg.contains("不能为空") {
                PyValueError::new_err(msg)
            } else {
                PyRuntimeError::new_err(msg)
            }
        })
    }

    #[staticmethod]
    #[pyo3(signature = (source_audio_path, output_wav_path, segments_samples))]
    pub fn build_wav_timeline_from_samples(
        py: Python<'_>,
        source_audio_path: String,
        output_wav_path: String,
        segments_samples: Vec<(u64, u64)>,
    ) -> PyResult<(usize, usize, u32, u16)> {
        py.allow_threads(|| {
            build_wav_timeline_from_samples_impl(
                &source_audio_path,
                &output_wav_path,
                &segments_samples,
            )
        })
        .map_err(|msg| {
            if msg.contains("仅支持") || msg.contains("非法片段") || msg.contains("不能为空") {
                PyValueError::new_err(msg)
            } else {
                PyRuntimeError::new_err(msg)
            }
        })
    }
}
