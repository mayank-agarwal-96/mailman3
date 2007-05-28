# Copyright (C) 2006-2007 by the Free Software Foundation, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301,
# USA.

from elixir import *
from email.utils import formataddr
from zope.interface import implements

from Mailman.interfaces import IAddress


ROSTER_KIND = 'Mailman.database.model.roster.Roster'
USER_KIND   = 'Mailman.database.model.user.User'


class Address(Entity):
    implements(IAddress)

    has_field('address',        Unicode)
    has_field('real_name',      Unicode)
    has_field('verified',       Boolean)
    has_field('registered_on',  DateTime)
    has_field('validated_on',   DateTime)
    # Relationships
    has_and_belongs_to_many('rosters', of_kind=ROSTER_KIND)
    belongs_to('user', of_kind=USER_KIND)

    def __str__(self):
        return formataddr((self.real_name, self.address))

    def __repr__(self):
        return '<Address: %s [%s]>' % (
            str(self), ('verified' if self.verified else 'not verified'))
