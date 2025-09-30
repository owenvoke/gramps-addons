"""
GBPN Gramplet.
"""

import csv
import logging
from pathlib import Path
from typing import Optional

from gi.repository import Gtk
from gramps.gen.datehandler import parser
from gramps.gen.db import DbReadBase, DbTxn, DbWriteBase

from gramps.gen.plug import Gramplet
from gramps.gen.lib import (
    Place,
    PlaceName,
    PlaceType,
    Url,
    PlaceRef,
    Date,
)

from gramps.gen.config import config
from gramps.gen.const import GRAMPS_LOCALE as glocale

from const import (
    INI_PREFERENCES_ALTERNATIVE_NAMES_ENABLED,
    INI_PREFERENCES_HIERARCHY_ENABLED,
    INI_HIERARCHY_ADMIN,
    INI_HIERARCHY_HISTORIC,
    INI_HIERARCHY_MODERN,
    INI_HIERARCHY_CIVIL_PARISH,
    INI_PREFERENCES_STRIP_CIVIL_PARISH_SUFFIX,
    DOMAIN,
)

try:
    _trans = glocale.get_addon_translator(__file__)
except ValueError:
    _trans = glocale.translation
_ = _trans.gettext

LOG = logging.getLogger(DOMAIN)

# Configuration
CONFIG = config.register_manager(DOMAIN)
CONFIG.register(INI_PREFERENCES_ALTERNATIVE_NAMES_ENABLED, True)
CONFIG.register(INI_PREFERENCES_HIERARCHY_ENABLED, True)
CONFIG.register(INI_PREFERENCES_STRIP_CIVIL_PARISH_SUFFIX, False)
CONFIG.register(INI_HIERARCHY_ADMIN, True)
CONFIG.register(INI_HIERARCHY_CIVIL_PARISH, True)
CONFIG.register(INI_HIERARCHY_HISTORIC, True)
CONFIG.register(INI_HIERARCHY_MODERN, True)
CONFIG.load()


class GBPN(Gramplet):
    """
    Import places from the Gazetteer of British Place Names into Gramps by GBPNID.
    """

    HISTORIC_COUNTIES_DATE_PERIOD = "before 1889-01-01"
    ADMINISTRATIVE_COUNTIES_DATE_PERIOD = "from 1889-01-01 to 1974-01-01"
    MODERN_REGIONS_DATE_PERIOD = "after 1974-01-01"

    # Config booleans
    _alternative_names_enabled: bool = None
    _hierarchy_enabled: bool = None
    _hierarchy_admin: bool = None
    _hierarchy_civil_parish: bool = None
    _hierarchy_historic: bool = None
    _hierarchy_modern: bool = None
    _strip_civil_parish_suffix: bool = None

    _gbpn_id: str = None

    def init(self):
        self._alternative_names_enabled = CONFIG.get(
            INI_PREFERENCES_ALTERNATIVE_NAMES_ENABLED
        )
        self._hierarchy_enabled = CONFIG.get(INI_PREFERENCES_HIERARCHY_ENABLED)
        self._hierarchy_historic = CONFIG.get(INI_HIERARCHY_HISTORIC)
        self._hierarchy_admin = CONFIG.get(INI_HIERARCHY_ADMIN)
        self._hierarchy_modern = CONFIG.get(INI_HIERARCHY_MODERN)
        self._hierarchy_civil_parish = CONFIG.get(INI_HIERARCHY_CIVIL_PARISH)
        self._strip_civil_parish_suffix = CONFIG.get(
            INI_PREFERENCES_STRIP_CIVIL_PARISH_SUFFIX
        )

        root = self.__create_gui()
        self.gui.get_container_widget().remove(self.gui.textview)
        self.gui.get_container_widget().add_with_viewport(root)
        root.show_all()

    def __create_gui(self):
        """
        Create and display the GUI components of the gramplet.
        """
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_left(10)
        vbox.set_margin_right(10)

        gbpn_id_label = Gtk.Label(
            _("ID to import from Gazetteer of British Place Names")
        )
        gbpn_id_label.set_halign(Gtk.Align.START)

        self.gbpn_id_entry = Gtk.Entry()

        self.errors_label = Gtk.Label()
        self.errors_label.set_halign(Gtk.Align.START)

        button_box = Gtk.ButtonBox()
        button_box.set_layout(Gtk.ButtonBoxStyle.START)

        get = Gtk.Button(label=_("Import place"))
        get.connect("clicked", self.__get_places)
        button_box.add(get)

        vbox.pack_start(gbpn_id_label, False, True, 0)
        vbox.pack_start(self.gbpn_id_entry, False, True, 0)
        vbox.pack_start(self.errors_label, False, True, 0)
        vbox.pack_start(button_box, False, True, 0)

        return vbox

    def main(self):
        pass

    def __get_places(self, obj):
        count = 0

        self._gbpn_id = self.gbpn_id_entry.get_text()

        if self._gbpn_id == "" or not self._gbpn_id.isdigit():
            self.errors_label.set_text(_("Please enter a valid GBPN ID"))
            return

        csv_path = Path(__file__).parent / "GBPN.csv"
        if not csv_path.exists():
            LOG.warning("File not found: %s", csv_path)
            self.errors_label.set_text(
                _("File not found: %(file_name)s") % {"file_name": csv_path}
            )
            return

        LOG.debug(
            "Starting import from %s for GBPN ID: %s",
            csv_path,
            self._gbpn_id,
        )

        self.errors_label.set_text("")

        with open(csv_path, encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                gbpn_id = row.get("GBPNID", "")
                name_type = row.get("NameType", "").upper()

                if gbpn_id != self._gbpn_id or name_type != "P":
                    continue

                place_name = row.get("PlaceName", "")
                gbpn_url = row.get("GBPN_URL", "")
                latitude = row.get("Lat", "")
                longitude = row.get("Lng", "")
                place_type = row.get("Type", "")
                alternative_names = row.get("Alternative_Name", "")

                with DbTxn(
                    _("Handle GBPN place: %(place_name)s (%(gbpn_id)s)")
                    % {"place_name": place_name, "gbpn_id": gbpn_id},
                    self.dbstate.db,
                ) as trans:
                    __, place = self.__ensure_place(
                        self.dbstate.db, trans, name=place_name, place_type=place_type
                    )

                    # Set type
                    if (
                        place.get_type() is None
                        or place.get_type() == PlaceType.UNKNOWN
                    ):
                        place.set_type(place_type)
                        LOG.debug(" - Set type: %s", place_type.value)

                    # Coordinates
                    if (
                        (place.get_latitude() == "" or place.get_longitude() == "")
                        and latitude
                        and longitude
                    ):
                        place.set_latitude(latitude)
                        place.set_longitude(longitude)
                        LOG.debug(" - Set coordinates: %s, %s", latitude, longitude)

                    # GBPN URL
                    if gbpn_url:
                        add_url = True
                        for u in place.get_url_list():
                            if u.get_type() == "GBPN URL" and u.get_description() == (
                                _("Gazetteer of British Place Names (ID: %(gbpn_id)s)")
                                % {"gbpn_id": gbpn_id},
                            ):
                                add_url = False
                                break

                        existing_urls = {
                            u.get_path()
                            for u in place.get_url_list()
                            if u.get_type() == "GBPN URL"
                        }

                        if add_url and gbpn_url not in existing_urls:
                            url = self.__get_gbpn_url(gbpn_url, gbpn_id)
                            place.add_url(url)
                            LOG.debug(" - Added GBPN URL: %s", gbpn_url)

                    # Alternative names
                    if self._alternative_names_enabled:
                        existing_names = {
                            n.get_value() for n in place.get_alternative_names()
                        }
                        for alternative_name in [
                            n for n in alternative_names.split(",") if n
                        ]:
                            if alternative_name not in existing_names:
                                place.add_alternative_name(alternative_name)
                                LOG.debug(
                                    " - Added alternative name: '%s' to place: '%s'",
                                    alternative_name,
                                    place_name,
                                )
                            else:
                                LOG.debug(
                                    " - Skipped existing alternative name: '%s'",
                                    alternative_name,
                                )

                    original_enclosing_places = place.get_placeref_list().copy()
                    top = place
                    if self._hierarchy_enabled:
                        top = self.__generate_hierarchy(trans, place, row) or place
                    top.set_placeref_list(original_enclosing_places)

                    self.dbstate.db.commit_place(place, trans)
                    count += 1

        self.errors_label.set_text(
            _("Finished import: %(imported)d place(s) processed") % {"imported": count}
        )
        LOG.debug("Finished import: %d place(s) processed", count)

    # -------------------
    # Helpers
    # -------------------

    @staticmethod
    def __get_or_create_place(
        db: DbWriteBase, name: str, place_type: int, parent_handle=None
    ) -> Place:
        for place in db.iter_places():
            if name == place.get_name().get_value() and place_type == place.get_type():
                return place

        new_place = Place()
        new_place_name = PlaceName()
        new_place_name.set_value(name)
        new_place.set_name(new_place_name)
        new_place.set_type(place_type)

        if parent_handle is not None:
            parent_ref = PlaceRef()
            parent_ref.set_reference_handle(parent_handle)
            new_place.add_placeref(parent_ref)

        return new_place

    @staticmethod
    def __normalize_parish_name(name: str, strip_suffix: bool = True) -> str:
        """Strip 'CP' from CivilParish names and trim whitespace."""
        if strip_suffix and name.endswith(" CP"):
            name = name[:-3]
        return name

    @staticmethod
    def __find_existing_place(
        db: DbReadBase, name: str, gbpn_id: str
    ) -> Optional[Place]:
        if gbpn_id:
            for place in db.iter_places():
                for url in place.get_url_list():
                    if url.get_type() == "GBPN URL" and url.get_description() == (
                        _("Gazetteer of British Place Names (ID: %(gbpn_id)s)")
                        % {"gbpn_id": gbpn_id},
                    ):
                        return place
        for place in db.iter_places():
            if place.get_name().get_value() == name:
                return place
        return None

    def __generate_hierarchy(self, trans: DbTxn, place: Place, row: dict):
        """
        Build hierarchy with explicit PlaceTypes and time-scoped parents:

          United Kingdom [COUNTRY]
            -> Region [STATE]
              -> Historic County [COUNTY] (before 1889-01-01) (there can be multiple)
              -> Administrative County [COUNTY] (from 1889-01-01 to 1974-01-01)
                  -> District [DISTRICT] (same admin period)
              -> Unitary Authority [COUNTY] (after 1974-01-01)
                  -> Parish [PARISH] (if CivilParish exists; also under the Administrative County path if applicable)
        """
        db = self.dbstate.db

        # CSV fields
        region = row.get("Region", "")
        historic_county_raw = row.get("HistCounty", "")
        ad_county = row.get("AdCounty", "")
        district = row.get("District", "")
        uni_auth = row.get("UniAuth", "")
        civil_parish_raw = row.get("CivilParish", "")
        civil_parish = (
            self.__normalize_parish_name(
                civil_parish_raw, self._strip_civil_parish_suffix
            )
            if civil_parish_raw
            else ""
        )

        # 1) United Kingdom (COUNTRY)
        uk_handle, uk_place = self.__ensure_place(
            db,
            trans,
            name="United Kingdom",
            place_type=PlaceType.COUNTRY,
            parent_handle=None,
        )

        # 2) Region (STATE) under UK  (use PlaceType.REGION if available in your Gramps build)
        region_handle = uk_handle
        if region:
            region_handle, _ = self.__ensure_place(
                db,
                trans,
                name=region,
                place_type=PlaceType.COUNTRY,
                parent_handle=uk_handle,
            )

        # 3) Historic County [COUNTY] under Region (supports multiple, slash-separated)
        hist_parent_handles: list[str] = []
        if self._hierarchy_historic and historic_county_raw:
            parts = [p.strip() for p in historic_county_raw.split("/") if p.strip()]
            # de-duplicate while preserving order
            seen = set()
            hist_names = [p for p in parts if not (p in seen or seen.add(p))]
            for hist_name in hist_names:
                h_handle, _ = self.__ensure_place(
                    db,
                    trans,
                    name=hist_name,
                    place_type=PlaceType.COUNTY,
                    parent_handle=region_handle,
                )
                hist_parent_handles.append(h_handle)

        # 4) Admin County [COUNTY] and optional District [DISTRICT] under Region
        admin_parent_handle = None
        district_parent_handle = None
        if self._hierarchy_admin and ad_county:
            admin_parent_handle, _ = self.__ensure_place(
                db,
                trans,
                name=ad_county,
                place_type=PlaceType.COUNTY,
                parent_handle=region_handle,
            )
            if district:
                district_parent_handle, _ = self.__ensure_place(
                    db,
                    trans,
                    name=district,
                    place_type=PlaceType.DISTRICT,
                    parent_handle=admin_parent_handle,
                )

        # 5) Unitary Authority [COUNTY] under Region
        ua_parent_handle = None
        if self._hierarchy_modern and uni_auth:
            ua_parent_handle, _ = self.__ensure_place(
                db,
                trans,
                name=uni_auth,
                place_type=PlaceType.COUNTY,
                parent_handle=region_handle,
            )

        # 6) Parish [PARISH] (if CivilParish exists)
        #    - Under District if present (admin path), else under Admin County
        #    - Under Unitary Authority for the modern path
        parish_admin_handle = None
        parish_modern_handle = None
        if self._hierarchy_civil_parish and civil_parish:
            # Admin path parish
            if district_parent_handle:
                parish_admin_handle, _ = self.__ensure_place(
                    db,
                    trans,
                    name=civil_parish,
                    place_type=PlaceType.PARISH,
                    parent_handle=district_parent_handle,
                )
            elif admin_parent_handle:
                parish_admin_handle, _ = self.__ensure_place(
                    db,
                    trans,
                    name=civil_parish,
                    place_type=PlaceType.PARISH,
                    parent_handle=admin_parent_handle,
                )

            # Modern path parish
            if ua_parent_handle:
                parish_modern_handle, _ = self.__ensure_place(
                    db,
                    trans,
                    name=civil_parish,
                    place_type=PlaceType.PARISH,
                    parent_handle=ua_parent_handle,
                )

        # 7) Build PlaceRefs for the current place with date ranges
        new_refs: list[PlaceRef] = []

        # Historic: attach one ref per historic county
        if self._hierarchy_historic and hist_parent_handles:
            for h in hist_parent_handles:
                pr = PlaceRef()
                pr.set_reference_handle(h)
                pr.set_date_object(
                    self.__get_date_range(self.HISTORIC_COUNTIES_DATE_PERIOD)
                )
                new_refs.append(pr)

        # Administrative (1889-01-01 to 1974-01-01): deepest parent available
        admin_deepest = (
            parish_admin_handle or district_parent_handle or admin_parent_handle
        )
        if self._hierarchy_admin and admin_deepest:
            pr = PlaceRef()
            pr.set_reference_handle(admin_deepest)
            pr.set_date_object(
                self.__get_date_range(self.ADMINISTRATIVE_COUNTIES_DATE_PERIOD)
            )
            new_refs.append(pr)

        # Modern (after 1974-01-01): deepest parent available (prefer parish under UA)
        modern_deepest = parish_modern_handle or ua_parent_handle
        if self._hierarchy_modern and modern_deepest:
            pr = PlaceRef()
            pr.set_reference_handle(modern_deepest)
            pr.set_date_object(self.__get_date_range(self.MODERN_REGIONS_DATE_PERIOD))
            new_refs.append(pr)

        # Fallback: if nothing above, at least attach to Region (no date)
        if not new_refs and region_handle and region_handle != uk_handle:
            pr = PlaceRef()
            pr.set_reference_handle(region_handle)
            new_refs.append(pr)

        # Apply new enclosing parents
        place.set_placeref_list(new_refs)

        return uk_place

    @staticmethod
    def __ensure_place(
        db: DbWriteBase,
        trans: DbTxn,
        name: str,
        place_type: int | str,
        parent_handle: Optional[str] = None,
    ) -> tuple[str, Place]:
        """
        Get an existing place by exact (name, type) or create it, ensuring the parent chain exists.
        Returns (handle, place).
        """
        for handle in db.get_place_handles():
            p = db.get_place_from_handle(handle)
            if (
                p.get_name()
                and p.get_name().get_value() == name
                and p.get_type() == place_type
            ):
                # Ensure this place has the requested parent (without duplicating refs)
                if parent_handle:
                    existing_parent_handles = {r.ref for r in p.get_placeref_list()}
                    if parent_handle not in existing_parent_handles:
                        pr = PlaceRef()
                        pr.set_reference_handle(parent_handle)
                        p.add_placeref(pr)
                        db.commit_place(p, trans)
                return handle, p

        new_place = Place()
        pn = PlaceName()
        pn.set_value(name)
        new_place.set_name(pn)
        new_place.set_type(place_type)

        if parent_handle:
            pr = PlaceRef()
            pr.set_reference_handle(parent_handle)
            new_place.add_placeref(pr)
        handle = db.add_place(new_place, trans)
        return handle, new_place

    @staticmethod
    def __get_gbpn_url(value: str, gbpn_id: str) -> Url:
        url = Url()
        url.set_path(value)
        url.set_type("GBPN URL")
        url.set_description(
            _("Gazetteer of British Place Names (ID: %(gbpn_id)s)")
            % {"gbpn_id": gbpn_id},
        )
        return url

    @staticmethod
    def __get_date_range(date_str: str) -> Date:
        return parser.parse(date_str)

    # ======================================================
    # gramplet event handlers
    # ======================================================

    def on_save(self, *args, **kwargs):
        # Preferences
        CONFIG.set(
            INI_PREFERENCES_ALTERNATIVE_NAMES_ENABLED, self._alternative_names_enabled
        )
        CONFIG.set(INI_PREFERENCES_HIERARCHY_ENABLED, self._hierarchy_enabled)
        CONFIG.set(
            INI_PREFERENCES_STRIP_CIVIL_PARISH_SUFFIX,
            self._strip_civil_parish_suffix,
        )

        # Hierarchy
        CONFIG.set(INI_HIERARCHY_ADMIN, self._hierarchy_admin)
        CONFIG.set(INI_HIERARCHY_CIVIL_PARISH, self._hierarchy_civil_parish)
        CONFIG.set(INI_HIERARCHY_HISTORIC, self._hierarchy_historic)
        CONFIG.set(INI_HIERARCHY_MODERN, self._hierarchy_modern)

        CONFIG.save()
