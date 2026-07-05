use byteorder::{BigEndian, ByteOrder, LittleEndian};
use flate2::read::GzDecoder;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Endian {
    Little,
    Big,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DType {
    U2,
    U4,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct FieldSpec {
    name: &'static str,
    dtype: DType,
    shape: Vec<usize>,
}

#[derive(Debug, Clone, PartialEq)]
enum HeaderValue {
    Integer(u32),
    Float(f64),
}

#[derive(Debug)]
struct DecodedPace {
    sensor: i32,
    headers: Vec<BTreeMap<String, HeaderValue>>,
    records: Vec<DecodedRecord>,
}

#[derive(Debug)]
struct DecodedRecord {
    record_type: u32,
    arrays: BTreeMap<String, DecodedArray>,
}

#[derive(Debug)]
struct DecodedArray {
    dtype: DType,
    endian: Endian,
    shape: Vec<usize>,
    bytes: Vec<u8>,
}

#[derive(Debug, thiserror::Error)]
enum PaceError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Message(String),
}

#[pyfunction]
fn read_pace_pbf<'py>(py: Python<'py>, files: Vec<String>) -> PyResult<Bound<'py, PyDict>> {
    let paths: Vec<PathBuf> = files.into_iter().map(PathBuf::from).collect();
    let decoded = py
        .detach(|| decode_files(&paths))
        .map_err(pace_error_to_py)?;
    decoded_to_py(py, decoded)
}

#[pymodule]
fn sopran_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(read_pace_pbf, module)?)?;
    Ok(())
}

fn pace_error_to_py(error: PaceError) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

fn decoded_to_py<'py>(py: Python<'py>, decoded: DecodedPace) -> PyResult<Bound<'py, PyDict>> {
    let out = PyDict::new(py);
    out.set_item("sensor", decoded.sensor)?;

    let headers = PyList::empty(py);
    for header in decoded.headers {
        let header_dict = PyDict::new(py);
        for (key, value) in header {
            match value {
                HeaderValue::Integer(value) => header_dict.set_item(key, value)?,
                HeaderValue::Float(value) => header_dict.set_item(key, value)?,
            }
        }
        headers.append(header_dict)?;
    }
    out.set_item("headers", headers)?;

    let records = PyList::empty(py);
    for (index, record) in decoded.records.into_iter().enumerate() {
        let record_dict = PyDict::new(py);
        record_dict.set_item("type", record.record_type)?;
        record_dict.set_item("index", index)?;
        let arrays = PyDict::new(py);
        for (name, array) in record.arrays {
            let array_dict = PyDict::new(py);
            array_dict.set_item("dtype", array.dtype.numpy_name(array.endian))?;
            array_dict.set_item("shape", array.shape)?;
            array_dict.set_item("data", PyBytes::new(py, &array.bytes))?;
            arrays.set_item(name, array_dict)?;
        }
        record_dict.set_item("arrays", arrays)?;
        records.append(record_dict)?;
    }
    out.set_item("records", records)?;

    Ok(out)
}

fn decode_files(files: &[PathBuf]) -> Result<DecodedPace, PaceError> {
    let mut merged = DecodedPace {
        sensor: -1,
        headers: Vec::new(),
        records: Vec::new(),
    };

    for path in files {
        let bytes = read_file_bytes(path)?;
        let source_name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("PACE PBF file");
        let decoded = decode_pbf_bytes(&bytes, source_name)?;
        if decoded.sensor >= 0 {
            merged.sensor = decoded.sensor;
        }
        merged.headers.extend(decoded.headers);
        merged.records.extend(decoded.records);
    }

    Ok(merged)
}

fn choose_endian(header: &[u8]) -> Endian {
    for endian in [Endian::Little, Endian::Big] {
        let pbf_type = read_u32_at(header, 3, endian).unwrap_or(0);
        let yyyymmdd = read_u32_at(header, 19, endian).unwrap_or(0);
        let hhmmss = read_u32_at(header, 20, endian).unwrap_or(u32::MAX);
        if spec_for(pbf_type).is_some()
            && (20000101..=20300101).contains(&yyyymmdd)
            && hhmmss <= 235959
        {
            return endian;
        }
    }
    Endian::Little
}

fn spec_for(record_type: u32) -> Option<Vec<FieldSpec>> {
    let u2 = DType::U2;
    let u4 = DType::U4;
    let spec = match record_type {
        0x00 => vec![
            field("event", u4, &[16]),
            field("cnt", u2, &[32, 16, 64]),
            field("trash", u2, &[32, 16, 2]),
        ],
        0x01 => vec![
            field("event", u4, &[16]),
            field("cnt", u2, &[32, 4, 16]),
            field("trash", u2, &[32, 4, 2]),
        ],
        0x02 => vec![field("event", u4, &[16]), field("cnt", u2, &[32, 32])],
        0x03 => vec![
            field("event", u4, &[16]),
            field("cnt", u2, &[32, 8, 64]),
            field("trash", u2, &[32, 8, 2]),
        ],
        0x40 => vec![
            field("event", u4, &[4, 16]),
            field("cnt", u2, &[4, 32, 1024]),
        ],
        0x41 => vec![
            field("event", u4, &[4, 16]),
            field("cnt", u2, &[32, 16, 64]),
            field("trash", u2, &[32, 16, 2]),
        ],
        0x42 => vec![
            field("event", u4, &[4, 16]),
            field("cnt", u2, &[32, 4, 16]),
            field("trash", u2, &[32, 4, 2]),
        ],
        0x43 => vec![
            field("event", u4, &[4, 16]),
            field("cnt", u2, &[8, 32, 4, 16]),
            field("trash", u2, &[8, 32, 4, 2]),
        ],
        0x44 => vec![
            field("event", u4, &[4, 16]),
            field("s_cnt", u2, &[16, 32, 64]),
            field("cnt", u2, &[16, 32, 16, 64]),
        ],
        0x45 => vec![
            field("event", u4, &[4, 16]),
            field("cnt", u2, &[16, 32, 4, 16]),
            field("trash", u2, &[16, 32, 4, 2]),
        ],
        0x80 => vec![
            field("event", u4, &[16]),
            field("cnt", u2, &[32, 4, 16]),
            field("trash", u2, &[32, 4, 2]),
        ],
        0x81 => vec![
            field("event", u4, &[16]),
            field("cnt", u2, &[32, 16, 64]),
            field("trash", u2, &[32, 16, 2]),
        ],
        0x82 => vec![
            field("event", u4, &[16]),
            field("s_cnt", u2, &[32, 128]),
            field("cnt", u2, &[32, 16, 64]),
        ],
        _ => return None,
    };
    Some(spec)
}

fn payload_size(spec: &[FieldSpec]) -> usize {
    spec.iter()
        .map(|field| field.dtype.byte_size() * field.shape.iter().product::<usize>())
        .sum()
}

fn decode_pbf_bytes(bytes: &[u8], source_name: &str) -> Result<DecodedPace, PaceError> {
    if bytes.len() < 1024 {
        return Err(PaceError::Message(format!(
            "PACE PBF file is missing the 1024-byte file header: {source_name}"
        )));
    }
    let mut offset = 1024;
    let mut headers = Vec::new();
    let mut records = Vec::new();
    let mut detected_sensor = None;

    while offset < bytes.len() {
        if bytes.len() - offset < 256 {
            return Err(PaceError::Message(format!(
                "Truncated PACE PBF record header in {source_name}"
            )));
        }
        let header_bytes = &bytes[offset..offset + 256];
        offset += 256;
        let endian = choose_endian(header_bytes);
        let header = parse_header(header_bytes, endian)?;
        let record_type = match header.get("type") {
            Some(HeaderValue::Integer(value)) => *value,
            _ => {
                return Err(PaceError::Message(
                    "PACE PBF header is missing type".to_string(),
                ))
            }
        };
        let spec = spec_for(record_type).ok_or_else(|| {
            PaceError::Message(format!(
                "Unsupported PACE PBF record type 0x{record_type:02X} in {source_name}"
            ))
        })?;
        let size = payload_size(&spec);
        if bytes.len() - offset < size {
            return Err(PaceError::Message(format!(
                "Truncated PACE PBF payload for type 0x{record_type:02X} in {source_name}"
            )));
        }
        let arrays = read_payload(&bytes[offset..offset + size], &spec, endian)?;
        offset += size;
        detected_sensor = match header.get("sensor") {
            Some(HeaderValue::Integer(value)) => Some(*value as i32),
            _ => None,
        };
        headers.push(header);
        records.push(DecodedRecord {
            record_type,
            arrays,
        });
    }

    Ok(DecodedPace {
        sensor: detected_sensor.unwrap_or_else(|| detect_sensor(source_name)),
        headers,
        records,
    })
}

fn read_file_bytes(path: &Path) -> Result<Vec<u8>, PaceError> {
    let file = File::open(path)?;
    let mut reader: Box<dyn Read> =
        if path.extension().and_then(|value| value.to_str()) == Some("gz") {
            Box::new(GzDecoder::new(file))
        } else {
            Box::new(file)
        };
    let mut bytes = Vec::new();
    reader.read_to_end(&mut bytes)?;
    Ok(bytes)
}

fn parse_header(header: &[u8], endian: Endian) -> Result<BTreeMap<String, HeaderValue>, PaceError> {
    let mut out = BTreeMap::new();
    for (index, name) in HEADER_FIELDS.iter().enumerate() {
        let value = read_u32_at(header, index, endian).ok_or_else(|| {
            PaceError::Message("PACE PBF record header must contain 64 u32 values".to_string())
        })?;
        out.insert((*name).to_string(), HeaderValue::Integer(value));
    }
    if let (
        Some(HeaderValue::Integer(date)),
        Some(HeaderValue::Integer(time)),
        Some(HeaderValue::Integer(resolution)),
    ) = (
        out.get("yyyymmdd"),
        out.get("hhmmss"),
        out.get("time_resolution"),
    ) {
        if let Some(decoded) = decode_unix_time(*date, *time, *resolution) {
            out.insert("time".to_string(), HeaderValue::Float(decoded));
        }
    }
    Ok(out)
}

fn read_payload(
    payload: &[u8],
    spec: &[FieldSpec],
    endian: Endian,
) -> Result<BTreeMap<String, DecodedArray>, PaceError> {
    let mut arrays = BTreeMap::new();
    let mut offset = 0;
    for field in spec {
        let count = field.shape.iter().product::<usize>();
        let size = field.dtype.byte_size() * count;
        let end = offset + size;
        if end > payload.len() {
            return Err(PaceError::Message(format!(
                "Truncated PACE PBF payload field {}",
                field.name
            )));
        }
        arrays.insert(
            field.name.to_string(),
            DecodedArray {
                dtype: field.dtype,
                endian,
                shape: field.shape.clone(),
                bytes: payload[offset..end].to_vec(),
            },
        );
        offset = end;
    }
    Ok(arrays)
}

fn field(name: &'static str, dtype: DType, shape: &[usize]) -> FieldSpec {
    FieldSpec {
        name,
        dtype,
        shape: shape.to_vec(),
    }
}

fn read_u32_at(header: &[u8], index: usize, endian: Endian) -> Option<u32> {
    let start = index.checked_mul(4)?;
    let end = start.checked_add(4)?;
    if end > header.len() {
        return None;
    }
    let bytes = &header[start..end];
    Some(match endian {
        Endian::Little => LittleEndian::read_u32(bytes),
        Endian::Big => BigEndian::read_u32(bytes),
    })
}

fn decode_unix_time(yyyymmdd: u32, hhmmss: u32, time_resolution: u32) -> Option<f64> {
    let year = (yyyymmdd / 10000) as i32;
    let month = (yyyymmdd / 100 % 100) as u32;
    let day = (yyyymmdd % 100) as u32;
    let hour = hhmmss / 10000;
    let minute = hhmmss / 100 % 100;
    let second = hhmmss % 100;
    if !valid_date(year, month, day) || hour > 23 || minute > 59 || second > 59 {
        return None;
    }
    let days = days_from_civil(year, month, day);
    let seconds = days * 86_400 + hour as i64 * 3_600 + minute as i64 * 60 + second as i64;
    Some(seconds as f64 + time_resolution as f64 * 0.5e-3)
}

fn valid_date(year: i32, month: u32, day: u32) -> bool {
    if !(1..=12).contains(&month) {
        return false;
    }
    let max_day = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if is_leap_year(year) => 29,
        2 => 28,
        _ => return false,
    };
    (1..=max_day).contains(&day)
}

fn is_leap_year(year: i32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

fn days_from_civil(year: i32, month: u32, day: u32) -> i64 {
    let adjusted_year = year - if month <= 2 { 1 } else { 0 };
    let era = if adjusted_year >= 0 {
        adjusted_year
    } else {
        adjusted_year - 399
    } / 400;
    let year_of_era = adjusted_year - era * 400;
    let month = month as i32;
    let day = day as i32;
    let day_of_year = (153 * (month + if month > 2 { -3 } else { 9 }) + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    (era * 146_097 + day_of_era - 719_468) as i64
}

fn detect_sensor(source_name: &str) -> i32 {
    let name = source_name.to_ascii_uppercase();
    if name.contains("ESA1") || name.contains("ESA-S1") || name.contains("ESAS1") {
        0
    } else if name.contains("ESA2") || name.contains("ESA-S2") || name.contains("ESAS2") {
        1
    } else if name.contains("IMA") {
        2
    } else if name.contains("IEA") {
        3
    } else {
        -1
    }
}

impl DType {
    fn byte_size(self) -> usize {
        match self {
            DType::U2 => 2,
            DType::U4 => 4,
        }
    }

    fn numpy_name(self, endian: Endian) -> &'static str {
        match (endian, self) {
            (Endian::Little, DType::U2) => "<u2",
            (Endian::Little, DType::U4) => "<u4",
            (Endian::Big, DType::U2) => ">u2",
            (Endian::Big, DType::U4) => ">u4",
        }
    }
}

const HEADER_FIELDS: &[&str] = &[
    "sensor",
    "mode",
    "mode2",
    "type",
    "size",
    "time_resolution",
    "sampl_time",
    "ver",
    "tbl_ver",
    "obs_ver",
    "timeH",
    "timeM",
    "timeL",
    "bc",
    "ic",
    "sc",
    "sc_step0",
    "t_date",
    "time_ms",
    "yyyymmdd",
    "hhmmss",
    "tof_tbl",
    "pd_pha",
    "svg_tbl",
    "sva_tbl",
    "svs_tbl",
    "obs_tbl",
    "obs_ctr",
    "nv_high",
    "nv_low",
    "data_quality",
    "pol_step",
    "az_step",
    "ene_step",
    "mass_step",
    "pitch_step",
    "tof_step",
    "solwnd_step",
    "exb_step",
    "event_step",
    "trash_step",
    "tof_disc_start",
    "tof_disc_stop",
    "hv_scan_level",
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pace_choose_endian_accepts_big_endian_headers() {
        let mut header = vec![0_u8; 256];
        put_u32_be(&mut header, 3, 0x01);
        put_u32_be(&mut header, 19, 20080101);
        put_u32_be(&mut header, 20, 123456);

        assert_eq!(choose_endian(&header), Endian::Big);
    }

    #[test]
    fn pace_type01_payload_size_matches_python_spec() {
        let spec = spec_for(0x01).expect("type 0x01 spec");

        assert_eq!(payload_size(&spec), 4672);
    }

    #[test]
    fn pace_decode_type01_synthetic_record() {
        let bytes = synthetic_type01_file();

        let decoded = decode_pbf_bytes(&bytes, "IPACE_PBF1_080101_ESA1_V003.dat")
            .expect("synthetic PBF decodes");

        assert_eq!(decoded.headers.len(), 1);
        assert_eq!(decoded.records.len(), 1);
        assert_eq!(
            decoded.headers[0].get("type"),
            Some(&HeaderValue::Integer(0x01))
        );
        assert_eq!(
            decoded.headers[0].get("time"),
            Some(&HeaderValue::Float(1199145608.0))
        );
        assert_eq!(decoded.records[0].record_type, 0x01);
        let counts = decoded.records[0].arrays.get("cnt").expect("cnt array");
        assert_eq!(counts.dtype, DType::U2);
        assert_eq!(counts.endian, Endian::Little);
        assert_eq!(counts.shape, vec![32, 4, 16]);
        assert_eq!(counts.bytes.len(), 32 * 4 * 16 * 2);
        assert!(counts.bytes.chunks_exact(2).all(|chunk| chunk == [1, 0]));
    }

    fn synthetic_type01_file() -> Vec<u8> {
        let mut bytes = vec![0_u8; 1024];
        let mut header = vec![0_u8; 256];
        put_u32_le(&mut header, 0, 0);
        put_u32_le(&mut header, 3, 0x01);
        put_u32_le(&mut header, 5, 16000);
        put_u32_le(&mut header, 6, 16);
        put_u32_le(&mut header, 19, 20080101);
        put_u32_le(&mut header, 20, 0);
        bytes.extend_from_slice(&header);

        for value in 0_u32..16 {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        for _ in 0..(32 * 4 * 16) {
            bytes.extend_from_slice(&1_u16.to_le_bytes());
        }
        for _ in 0..(32 * 4 * 2) {
            bytes.extend_from_slice(&0_u16.to_le_bytes());
        }
        bytes
    }

    fn put_u32_le(header: &mut [u8], index: usize, value: u32) {
        header[index * 4..index * 4 + 4].copy_from_slice(&value.to_le_bytes());
    }

    fn put_u32_be(header: &mut [u8], index: usize, value: u32) {
        header[index * 4..index * 4 + 4].copy_from_slice(&value.to_be_bytes());
    }
}
