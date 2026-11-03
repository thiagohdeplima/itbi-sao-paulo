"""Source headers, internal column names, and identifier types."""

import pandas as pd

# The source uses the same 28 column positions across monthly worksheets.
# Portuguese literals are source data, not application identifiers.
COLUMN_NAMES = {
    "N° do Cadastro (SQL)": "property_tax_id",
    "Nome do Logradouro": "street_name",
    "Número": "street_number",
    "Complemento": "address_complement",
    "Bairro": "neighborhood",
    "Referência": "address_reference",
    "CEP": "postal_code",
    "Natureza de Transação": "transaction_nature",
    "Valor de Transação (declarado pelo contribuinte)": "declared_transaction_value",
    "Data de Transação": "transaction_date",
    "Valor Venal de Referência": "reference_market_value",
    "Proporção Transmitida (%)": "transferred_share_pct",
    "Valor Venal de Referência (proporcional)": "proportional_reference_market_value",
    "Base de Cálculo adotada": "tax_calculation_base",
    "Tipo de Financiamento": "financing_type",
    "Valor Financiado": "financed_amount",
    "Cartório de Registro": "registry_office",
    "Matrícula do Imóvel": "property_registration_id",
    "Situação do SQL": "property_tax_status",
    "Área do Terreno (m2)": "land_area_m2",
    "Testada (m)": "frontage_m",
    "Fração Ideal": "ownership_fraction",
    "Área Construída (m2)": "built_area_m2",
    "Uso (IPTU)": "property_tax_use_code",
    "Descrição do uso (IPTU)": "property_tax_use_description",
    "Padrão (IPTU)": "property_tax_standard_code",
    "Descrição do padrão (IPTU)": "property_tax_standard_description",
    "ACC (IPTU)": "property_tax_adjusted_construction_year",
}
SOURCE_COLUMNS = tuple(COLUMN_NAMES)
COLUMNS = tuple(COLUMN_NAMES.values())
TEXT_COLUMNS = (
    "property_tax_id",
    "street_name",
    "street_number",
    "address_complement",
    "neighborhood",
    "address_reference",
    "postal_code",
    "transaction_nature",
    "financing_type",
    "registry_office",
    "property_registration_id",
    "property_tax_status",
    "property_tax_use_code",
    "property_tax_use_description",
    "property_tax_standard_code",
    "property_tax_standard_description",
)
# Match the numeric display masks in the source without adding punctuation.
CODE_WIDTHS = {
    "property_tax_id": 11,
    "postal_code": 8,
    "property_tax_use_code": 3,
    "property_tax_standard_code": 2,
}
MONTHLY_SHEET_PATTERN = r"(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)-\d{4}"
PURCHASE_TRANSACTION = "1.Compra e venda"


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Name positional source columns and preserve nullable string codes."""
    frame = frame.reindex(columns=range(len(COLUMNS)))
    frame.columns = COLUMNS
    frame = frame.astype({column: "string" for column in TEXT_COLUMNS})
    frame = frame.infer_objects()
    for column, width in CODE_WIDTHS.items():
        is_code = frame[column].str.fullmatch(rf"[0-9]{{1,{width}}}", na=False)
        frame.loc[is_code, column] = frame.loc[is_code, column].str.zfill(width)
    return frame
