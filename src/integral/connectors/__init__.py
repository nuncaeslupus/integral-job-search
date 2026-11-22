"""Declarative connector format, and the interpreter that runs it (T32).

A package since #928: `_base` (shared names), `markup` (selectors and the HTML tree),
`model` (schema, JSON paths, encodings), `read` (loading and interpretation) and
`probes` (the gates). Every name is re-exported here, so `integral.connectors.X`
keeps working. The design rationale is in `_base`'s docstring.
"""

from __future__ import annotations

from integral.connectors._base import (
    _DNS_LABEL as _DNS_LABEL,
)
from integral.connectors._base import (
    _KEY_SEPARATORS as _KEY_SEPARATORS,
)
from integral.connectors._base import (
    _KNOWN_PLACEHOLDER as _KNOWN_PLACEHOLDER,
)
from integral.connectors._base import (
    _REPO_ROOT as _REPO_ROOT,
)
from integral.connectors._base import (
    ALLOWED_OFFER_FIELDS as ALLOWED_OFFER_FIELDS,
)
from integral.connectors._base import (
    CONNECTOR_FILENAME as CONNECTOR_FILENAME,
)
from integral.connectors._base import (
    CREDENTIAL_KEY_QUALIFIERS as CREDENTIAL_KEY_QUALIFIERS,
)
from integral.connectors._base import (
    CREDENTIAL_KEY_TOKENS as CREDENTIAL_KEY_TOKENS,
)
from integral.connectors._base import (
    DEFAULT_CONNECTORS_DIR as DEFAULT_CONNECTORS_DIR,
)
from integral.connectors._base import (
    DEFAULT_EVIDENCE_PATH as DEFAULT_EVIDENCE_PATH,
)
from integral.connectors._base import (
    DEFAULT_STALE_AFTER_DAYS as DEFAULT_STALE_AFTER_DAYS,
)
from integral.connectors._base import (
    DOT_SEGMENTS as DOT_SEGMENTS,
)
from integral.connectors._base import (
    EMPLOYER_PLACEHOLDER as EMPLOYER_PLACEHOLDER,
)
from integral.connectors._base import (
    EMPLOYER_SLUG as EMPLOYER_SLUG,
)
from integral.connectors._base import (
    FIXTURE_DIRNAME as FIXTURE_DIRNAME,
)
from integral.connectors._base import (
    JSON_CONTENT_TYPE as JSON_CONTENT_TYPE,
)
from integral.connectors._base import (
    LIST_FIELD_NAMES as LIST_FIELD_NAMES,
)
from integral.connectors._base import (
    MAX_EMPLOYERS as MAX_EMPLOYERS,
)
from integral.connectors._base import (
    META_FILENAME as META_FILENAME,
)
from integral.connectors._base import (
    PAGE_PLACEHOLDER as PAGE_PLACEHOLDER,
)
from integral.connectors._base import (
    PROBE_DIRNAME as PROBE_DIRNAME,
)
from integral.connectors._base import (
    QUERY_PLACEHOLDER as QUERY_PLACEHOLDER,
)
from integral.connectors._base import (
    SEARCH_SOURCE as SEARCH_SOURCE,
)
from integral.connectors._base import (
    SITE_NAME as SITE_NAME,
)
from integral.connectors._base import (
    VERSION as VERSION,
)
from integral.connectors._base import (
    ConnectorError as ConnectorError,
)
from integral.connectors._base import (
    Strict as Strict,
)
from integral.connectors._base import (
    _employer_slot_problem as _employer_slot_problem,
)
from integral.connectors._base import (
    _spells_a_credential as _spells_a_credential,
)
from integral.connectors._base import (
    credential_keys as credential_keys,
)
from integral.connectors._base import (
    credential_query_keys as credential_query_keys,
)
from integral.connectors._base import (
    employer_in_host as employer_in_host,
)
from integral.connectors._base import (
    names_a_credential as names_a_credential,
)
from integral.connectors._base import (
    safe_urlsplit as safe_urlsplit,
)
from integral.connectors.markup import (
    _CANONICAL_EMPTY_COMMENT as _CANONICAL_EMPTY_COMMENT,
)
from integral.connectors.markup import (
    _NON_PROSE as _NON_PROSE,
)
from integral.connectors.markup import (
    _OPAQUE_TEXT_ELEMENTS as _OPAQUE_TEXT_ELEMENTS,
)
from integral.connectors.markup import (
    _OTHER_TOKEN as _OTHER_TOKEN,
)
from integral.connectors.markup import (
    _TAG_OPEN_RE as _TAG_OPEN_RE,
)
from integral.connectors.markup import (
    _TAG_TOKEN as _TAG_TOKEN,
)
from integral.connectors.markup import (
    _VOID_TAGS as _VOID_TAGS,
)
from integral.connectors.markup import (
    Node as Node,
)
from integral.connectors.markup import (
    SimpleSelector as SimpleSelector,
)
from integral.connectors.markup import (
    _comment_close_end as _comment_close_end,
)
from integral.connectors.markup import (
    _neutralise_unterminated_tail as _neutralise_unterminated_tail,
)
from integral.connectors.markup import (
    _opening_tag_name as _opening_tag_name,
)
from integral.connectors.markup import (
    _skip_opaque_element as _skip_opaque_element,
)
from integral.connectors.markup import (
    _TreeBuilder as _TreeBuilder,
)
from integral.connectors.markup import (
    compile_selector as compile_selector,
)
from integral.connectors.markup import (
    parse_html as parse_html,
)
from integral.connectors.markup import (
    select_all as select_all,
)
from integral.connectors.markup import (
    select_first as select_first,
)
from integral.connectors.model import (
    _BARE_WORKING_TIME as _BARE_WORKING_TIME,
)
from integral.connectors.model import (
    _BOMS as _BOMS,
)
from integral.connectors.model import (
    _CURRENCIES as _CURRENCIES,
)
from integral.connectors.model import (
    _CURRENCY_TOKEN as _CURRENCY_TOKEN,
)
from integral.connectors.model import (
    _GENERATED_CLASS as _GENERATED_CLASS,
)
from integral.connectors.model import (
    _INDEX_SEGMENT as _INDEX_SEGMENT,
)
from integral.connectors.model import (
    _JSON_PATH_INDEX as _JSON_PATH_INDEX,
)
from integral.connectors.model import (
    _JSON_PATH_KEY as _JSON_PATH_KEY,
)
from integral.connectors.model import (
    _LABEL as _LABEL,
)
from integral.connectors.model import (
    _MAGNITUDE as _MAGNITUDE,
)
from integral.connectors.model import (
    _MISSING as _MISSING,
)
from integral.connectors.model import (
    _NUMBER as _NUMBER,
)
from integral.connectors.model import (
    _PAGE_AS_QUERY_KEY_NAME as _PAGE_AS_QUERY_KEY_NAME,
)
from integral.connectors.model import (
    _PAGE_OUTSIDE_QUERY as _PAGE_OUTSIDE_QUERY,
)
from integral.connectors.model import (
    _PERIOD_AFTER_SLASH as _PERIOD_AFTER_SLASH,
)
from integral.connectors.model import (
    _QUERY_PAIR_SEPARATORS as _QUERY_PAIR_SEPARATORS,
)
from integral.connectors.model import (
    _SERVED_HOST_RE as _SERVED_HOST_RE,
)
from integral.connectors.model import (
    _STRICT_QUERY_PAIR_SEPARATOR as _STRICT_QUERY_PAIR_SEPARATOR,
)
from integral.connectors.model import (
    _TEXT_NODE_TAKES as _TEXT_NODE_TAKES,
)
from integral.connectors.model import (
    CLIENT_TARGET as CLIENT_TARGET,
)
from integral.connectors.model import (
    ENCODING_LABELS as ENCODING_LABELS,
)
from integral.connectors.model import (
    JSON_PATH as JSON_PATH,
)
from integral.connectors.model import (
    JSON_ROOT as JSON_ROOT,
)
from integral.connectors.model import (
    REPLACEMENT_LABELS as REPLACEMENT_LABELS,
)
from integral.connectors.model import (
    RESERVED_TLDS as RESERVED_TLDS,
)
from integral.connectors.model import (
    URL_TEMPLATE_SLOT as URL_TEMPLATE_SLOT,
)
from integral.connectors.model import (
    AuthMode as AuthMode,
)
from integral.connectors.model import (
    Client as Client,
)
from integral.connectors.model import (
    Connector as Connector,
)
from integral.connectors.model import (
    DetailPage as DetailPage,
)
from integral.connectors.model import (
    FieldSelector as FieldSelector,
)
from integral.connectors.model import (
    JsonField as JsonField,
)
from integral.connectors.model import (
    JsonSource as JsonSource,
)
from integral.connectors.model import (
    ListPage as ListPage,
)
from integral.connectors.model import (
    Pagination as Pagination,
)
from integral.connectors.model import (
    Take as Take,
)
from integral.connectors.model import (
    _as_float as _as_float,
)
from integral.connectors.model import (
    _json_documents as _json_documents,
)
from integral.connectors.model import (
    _json_record as _json_record,
)
from integral.connectors.model import (
    _literal_body_violations as _literal_body_violations,
)
from integral.connectors.model import (
    _number_text as _number_text,
)
from integral.connectors.model import (
    _numbers_in as _numbers_in,
)
from integral.connectors.model import (
    _page_placeholder_paths as _page_placeholder_paths,
)
from integral.connectors.model import (
    _placeholder_carrying_query_key_occurrences as _placeholder_carrying_query_key_occurrences,
)
from integral.connectors.model import (
    _present as _present,
)
from integral.connectors.model import (
    _query_key_occurrences as _query_key_occurrences,
)
from integral.connectors.model import (
    _query_key_position as _query_key_position,
)
from integral.connectors.model import (
    _query_pairs as _query_pairs,
)
from integral.connectors.model import (
    _refuse_unaccepted_generated_classes as _refuse_unaccepted_generated_classes,
)
from integral.connectors.model import (
    _render_path as _render_path,
)
from integral.connectors.model import (
    _resolve as _resolve,
)
from integral.connectors.model import (
    _take as _take,
)
from integral.connectors.model import (
    _templated_url as _templated_url,
)
from integral.connectors.model import (
    _url_page_positions as _url_page_positions,
)
from integral.connectors.model import (
    client_headers as client_headers,
)
from integral.connectors.model import (
    compile_path as compile_path,
)
from integral.connectors.model import (
    compile_url_template as compile_url_template,
)
from integral.connectors.model import (
    decode_body as decode_body,
)
from integral.connectors.model import (
    dig as dig,
)
from integral.connectors.model import (
    dig_container as dig_container,
)
from integral.connectors.model import (
    encoding_for as encoding_for,
)
from integral.connectors.model import (
    generated_classes as generated_classes,
)
from integral.connectors.model import (
    query_pair_names as query_pair_names,
)
from integral.connectors.model import (
    serialise_body as serialise_body,
)
from integral.connectors.probes import (
    _ARRAY_PATH_DOCUMENT as _ARRAY_PATH_DOCUMENT,
)
from integral.connectors.probes import (
    _OVERLONG_INDEX as _OVERLONG_INDEX,
)
from integral.connectors.probes import (
    ARRAY_PATH_CONTRACTS as ARRAY_PATH_CONTRACTS,
)
from integral.connectors.probes import (
    CHARSET_CONTRACTS as CHARSET_CONTRACTS,
)
from integral.connectors.probes import (
    MINIMUM_ARRAY_PATH_CONTRACTS as MINIMUM_ARRAY_PATH_CONTRACTS,
)
from integral.connectors.probes import (
    MINIMUM_CHARSET_CONTRACTS as MINIMUM_CHARSET_CONTRACTS,
)
from integral.connectors.probes import (
    MINIMUM_PARTIAL_EXTRACTION_CONTRACTS as MINIMUM_PARTIAL_EXTRACTION_CONTRACTS,
)
from integral.connectors.probes import (
    MINIMUM_PROBES as MINIMUM_PROBES,
)
from integral.connectors.probes import (
    PARTIAL_EXTRACTION_CONTRACTS as PARTIAL_EXTRACTION_CONTRACTS,
)
from integral.connectors.probes import (
    REFUSED as REFUSED,
)
from integral.connectors.probes import (
    ProbeReport as ProbeReport,
)
from integral.connectors.probes import (
    _captures_outside_their_charset as _captures_outside_their_charset,
)
from integral.connectors.probes import (
    _main as _main,
)
from integral.connectors.probes import (
    _Refused as _Refused,
)
from integral.connectors.probes import (
    _refused_as_replacement as _refused_as_replacement,
)
from integral.connectors.probes import (
    _refuses as _refuses,
)
from integral.connectors.probes import (
    _resolve_declared as _resolve_declared,
)
from integral.connectors.probes import (
    array_path_defects as array_path_defects,
)
from integral.connectors.probes import (
    measure_array_paths as measure_array_paths,
)
from integral.connectors.probes import (
    measure_charset as measure_charset,
)
from integral.connectors.probes import (
    partial_extraction_defects as partial_extraction_defects,
)
from integral.connectors.probes import (
    probe_connector_isolation as probe_connector_isolation,
)
from integral.connectors.probes import (
    write_array_path_evidence as write_array_path_evidence,
)
from integral.connectors.probes import (
    write_charset_evidence as write_charset_evidence,
)
from integral.connectors.probes import (
    write_evidence as write_evidence,
)
from integral.connectors.read import (
    ListingResult as ListingResult,
)
from integral.connectors.read import (
    ListRequest as ListRequest,
)
from integral.connectors.read import (
    Staleness as Staleness,
)
from integral.connectors.read import (
    _as_wage as _as_wage,
)
from integral.connectors.read import (
    _declares as _declares,
)
from integral.connectors.read import (
    _extract as _extract,
)
from integral.connectors.read import (
    _format as _format,
)
from integral.connectors.read import (
    _list_targets as _list_targets,
)
from integral.connectors.read import (
    _outside_annual_bound as _outside_annual_bound,
)
from integral.connectors.read import (
    _page_substituted as _page_substituted,
)
from integral.connectors.read import (
    _read as _read,
)
from integral.connectors.read import (
    _select_after_text as _select_after_text,
)
from integral.connectors.read import (
    accepts_query as accepts_query,
)
from integral.connectors.read import (
    assess_staleness as assess_staleness,
)
from integral.connectors.read import (
    build_list_requests as build_list_requests,
)
from integral.connectors.read import (
    build_list_urls as build_list_urls,
)
from integral.connectors.read import (
    build_offer as build_offer,
)
from integral.connectors.read import (
    build_search_offer as build_search_offer,
)
from integral.connectors.read import (
    collect_listing as collect_listing,
)
from integral.connectors.read import (
    connector_packages as connector_packages,
)
from integral.connectors.read import (
    load_connector as load_connector,
)
from integral.connectors.read import (
    load_connectors as load_connectors,
)
from integral.connectors.read import (
    parse_connector as parse_connector,
)
from integral.connectors.read import (
    parse_detail_page as parse_detail_page,
)
from integral.connectors.read import (
    parse_list_page as parse_list_page,
)
from integral.connectors.read import (
    source_kind_of as source_kind_of,
)
