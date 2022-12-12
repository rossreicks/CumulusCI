import typing as T
from functools import cached_property

from sqlalchemy import func, text
from sqlalchemy.orm import Query, aliased

from cumulusci.core.exceptions import BulkDataException

Criterion = T.Any


class LoadQueryExtender:
    """Class that transforms a load.py query with columns, filters, joins"""

    @cached_property
    def columns_to_add(*args) -> T.Optional[T.List]:
        return None

    @cached_property
    def filters_to_add(*args) -> T.Optional[T.List]:
        return None

    @cached_property
    def outerjoins_to_add(*args) -> T.Optional[T.List]:
        return None

    def __init__(self, mapping, metadata, model) -> None:
        self.mapping, self.metadata, self.model = mapping, metadata, model

    def add_columns(self, query: Query):
        """Add columns to the query"""
        if self.columns_to_add:
            query = query.add_columns(*self.columns_to_add)
        return query

    def add_filters(self, query: Query):
        """Add filters to the query"""
        if self.filters_to_add:
            return query.filter(*self.filters_to_add)
        return query

    def add_outerjoins(self, query: Query):
        """Add outer joins to the query"""
        if self.outerjoins_to_add:
            for table, condition in self.outerjoins_to_add:
                query = query.outerjoin(table, condition)
        return query


class AddLookupsToQuery(LoadQueryExtender):
    """Adds columns and joins relatinng to lookups"""

    def __init__(self, mapping, metadata, model) -> None:
        super().__init__(mapping, metadata, model)
        self.lookups = [
            lookup for lookup in self.mapping.lookups.values() if not lookup.after
        ]

    @cached_property
    def columns_to_add(self):
        for lookup in self.lookups:
            lookup.aliased_table = aliased(
                self.metadata.tables[f"{lookup.table}_sf_ids"]
            )
        return [lookup.aliased_table.columns.sf_id for lookup in self.lookups]

    @cached_property
    def outerjoins_to_add(self):
        # Outer join with lookup ids table:
        # returns main obj even if lookup is null
        def join_for_lookup(lookup):
            key_field = lookup.get_lookup_key_field(self.model)
            value_column = getattr(self.model, key_field)
            return (
                lookup.aliased_table,
                lookup.aliased_table.columns.id == ("" + value_column),
                # lookup.aliased_table.columns.id == func.concat(lookup.table, "-", value_column),
            )

        return [join_for_lookup(lookup) for lookup in self.lookups]


class AddRecordTypesToQuery(LoadQueryExtender):
    """Adds columns, joins and filters relatinng to recordtypes"""

    def __init__(self, mapping, metadata, model) -> None:
        super().__init__(mapping, metadata, model)
        if "RecordTypeId" in mapping.fields:
            self.rt_dest_table = metadata.tables[
                mapping.get_destination_record_type_table()
            ]
        else:
            self.rt_dest_table = None

    @cached_property
    def columns_to_add(self):
        if self.rt_dest_table is not None:
            return [self.rt_dest_table.columns.record_type_id]

    @cached_property
    def filters_to_add(self):
        if self.mapping.record_type and hasattr(self.model, "record_type"):
            return [self.model.record_type == self.mapping.record_type]

    @cached_property
    def outerjoins_to_add(self):
        if "RecordTypeId" in self.mapping.fields:
            try:
                rt_source_table = self.metadata.tables[
                    self.mapping.get_source_record_type_table()
                ]
            except KeyError as e:
                raise BulkDataException(
                    "A record type mapping table was not found in your dataset. "
                    f"Was it generated by extract_data? {e}",
                ) from e
            rt_dest_table = self.metadata.tables[
                self.mapping.get_destination_record_type_table()
            ]
            return [
                (
                    rt_source_table,
                    rt_source_table.columns.record_type_id
                    == getattr(self.model, self.mapping.fields["RecordTypeId"]),
                ),
                (
                    rt_dest_table,
                    rt_dest_table.columns.developer_name
                    == rt_source_table.columns.developer_name,
                ),
            ]


class AddMappingFiltersToQuery(LoadQueryExtender):
    """Adds filters relating to user-specified filters"""

    @cached_property
    def filters_to_add(self):
        if self.mapping.filters:
            return [text(f) for f in self.mapping.filters]


class AddPersonAccountsToQuery(LoadQueryExtender):
    """Add filters relating to Person accounts."""

    @cached_property
    def filters_to_add(self):
        """Filter out non-person account Contact records.
        Contact records for person accounts were already created by the system."""

        assert self.mapping.sf_object == "Contact"
        return [
            func.lower(self.model.__table__.columns.get("IsPersonAccount")) == "false"
        ]
