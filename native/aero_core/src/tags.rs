//! Etiquetas y propiedades de audio con `lofty` (fase R5 de docs/RUST.md).
//!
//! Devuelve lo mismo que `aero.core.metadata.read_tags` (mutagen): duración, bitrate, frecuencia, canales,
//! bits y, si el archivo tiene etiquetas, título, artista, álbum, artista del álbum, género, año y pista.
//! Si lofty no entiende el formato (WMA, vídeos MKV/AVI…), devuelve `None` y Python usa mutagen.

use lofty::prelude::*;
use lofty::tag::{ItemKey, Tag};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rayon::prelude::*;

#[derive(Default)]
pub struct Tags {
    duration: Option<f64>,
    bitrate: Option<u32>,
    sample_rate: Option<u32>,
    channels: Option<u8>,
    bits: Option<u8>,
    text: Option<[String; 6]>, // título, artista, álbum, artista del álbum, género, fecha
    track: String,
}

/// Como `metadata._int`: el primer grupo de cifras («3/12» → 3, «2019-05-01» → 2019).
fn first_int(text: &str) -> Option<i64> {
    let digits: String = text.chars().skip_while(|c| !c.is_ascii_digit()).take_while(|c| c.is_ascii_digit()).collect();
    digits.parse().ok()
}

fn get(tag: &Tag, keys: &[ItemKey]) -> String {
    for k in keys {
        if let Some(v) = tag.get_string(*k) {
            let v = v.trim();
            if !v.is_empty() {
                return v.to_string();
            }
        }
    }
    String::new()
}

pub fn read(path: &str) -> Option<Tags> {
    let tagged = lofty::read_from_path(path).ok()?;
    let p = tagged.properties();
    let mut out = Tags::default();
    let secs = p.duration().as_secs_f64();
    if secs > 0.0 {
        out.duration = Some(secs);
        out.bitrate = p.audio_bitrate().filter(|b| *b > 0).map(|b| b * 1000);
        out.sample_rate = p.sample_rate().filter(|v| *v > 0);
        out.channels = p.channels().filter(|v| *v > 0);
        out.bits = p.bit_depth().filter(|v| *v > 0);
    }
    let tag = tagged.primary_tag().or_else(|| tagged.first_tag());
    if let Some(tag) = tag {
        let text = [
            get(tag, &[ItemKey::TrackTitle]),
            get(tag, &[ItemKey::TrackArtist]),
            get(tag, &[ItemKey::AlbumTitle]),
            get(tag, &[ItemKey::AlbumArtist]),
            get(tag, &[ItemKey::Genre]),
            get(tag, &[ItemKey::RecordingDate, ItemKey::Year]),
        ];
        let track = get(tag, &[ItemKey::TrackNumber]);
        // Como mutagen «easy»: una etiqueta sin ninguno de estos campos (p. ej. solo el codificador) no cuenta.
        if text.iter().any(|t| !t.is_empty()) || !track.is_empty() {
            out.text = Some(text);
            out.track = track;
        }
    }
    Some(out)
}

pub fn to_dict<'py>(py: Python<'py>, t: &Tags) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    if let Some(s) = t.duration {
        d.set_item("duration", s)?;
        if let Some(v) = t.bitrate {
            d.set_item("bitrate", v)?;
        }
        if let Some(v) = t.sample_rate {
            d.set_item("sample_rate", v)?;
        }
        if let Some(v) = t.channels {
            d.set_item("channels", v)?;
        }
        if let Some(v) = t.bits {
            d.set_item("bits_per_sample", v)?;
        }
    }
    if let Some([title, artist, album, album_artist, genre, date]) = &t.text {
        d.set_item("title", title)?;
        d.set_item("artist", artist)?;
        d.set_item("album", album)?;
        d.set_item("album_artist", album_artist)?;
        d.set_item("genre", genre)?;
        d.set_item("year", first_int(date))?;
        d.set_item("track", first_int(&t.track))?;
    }
    Ok(d)
}

/// Etiquetas de un archivo (dict) o None si este lector no entiende el formato.
#[pyfunction]
pub fn read_tags(py: Python<'_>, path: String) -> PyResult<Option<Bound<'_, PyDict>>> {
    match py.detach(|| read(&path)) {
        Some(t) => Ok(Some(to_dict(py, &t)?)),
        None => Ok(None),
    }
}

/// Varias a la vez, en paralelo en todos los núcleos y sin el GIL (escaneo de la biblioteca).
#[pyfunction]
pub fn read_tags_many(py: Python<'_>, paths: Vec<String>) -> PyResult<Vec<Option<Bound<'_, PyDict>>>> {
    let all: Vec<Option<Tags>> = py.detach(|| paths.par_iter().map(|p| read(p)).collect());
    all.iter().map(|t| t.as_ref().map(|t| to_dict(py, t)).transpose()).collect()
}
