use pelite::pe64::{Pe, PeView};
use thiserror::Error;

pub const LANG_ID_EN: u16 = 0x0009;
pub const LANG_ID_JP: u16 = 0x0011;

#[derive(Debug, Error)]
pub enum DetectError {
    #[error("Executable doesn't contain version metadata")]
    MissingVersionMetadata,
    #[error("Executable doesn't contain language metadata")]
    MissingLanguageMetadata,
    #[error("Executable doesn't contain product name metadata")]
    MissingProductName,
    #[error("Expected executable name to be \"{expected}\", was \"{actual}\"")]
    WrongProduct {
        expected: &'static str,
        actual: String,
    },
    #[error(
        "Expected executable language ID to be {LANG_ID_EN:#04x} or {LANG_ID_JP:#04x}, was {0:#04x}"
    )]
    UnsupportedLanguage(u16),
    #[error("Unsupported game version {0}")]
    UnsupportedVersion(String),
}

pub trait GameVersion: Sized {
    const NAME: &'static str;

    fn from_lang_version(lang_id: u16, version: &str) -> Option<Self>;

    fn detect(module: &PeView) -> Result<Self, DetectError> {
        let resources = module.resources().unwrap();
        let info = resources.version_info().unwrap();

        let product_version = info
            .fixed()
            .ok_or(DetectError::MissingVersionMetadata)?
            .dwProductVersion;
        let version = format!(
            "{}.{}.{}.{}",
            product_version.Major,
            product_version.Minor,
            product_version.Patch,
            product_version.Build,
        );

        let language = *info
            .translation()
            .first()
            .ok_or(DetectError::MissingLanguageMetadata)?;
        let mut product_name: Option<String> = None;
        info.strings(language, |k, v| {
            if k == "ProductName" {
                product_name = Some(v.to_string());
            }
        });

        let product = product_name.ok_or(DetectError::MissingProductName)?;
        if normalize(&product) != Self::NAME {
            return Err(DetectError::WrongProduct {
                expected: Self::NAME,
                actual: product,
            });
        }

        let lang_id = language.lang_id & 0x03FF;
        if lang_id != LANG_ID_EN && lang_id != LANG_ID_JP {
            return Err(DetectError::UnsupportedLanguage(lang_id));
        }

        Self::from_lang_version(lang_id, &version).ok_or(DetectError::UnsupportedVersion(version))
    }
}

fn normalize(product: &str) -> String {
    product
        .chars()
        .filter(|c| c.is_alphanumeric() || c.is_whitespace())
        .collect::<String>()
        .to_lowercase()
}
