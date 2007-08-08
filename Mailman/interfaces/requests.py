# Copyright (C) 2007 by the Free Software Foundation, Inc.
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

"""Interfaces for the request database.

The request database handles events that must be approved by the list
moderators, such as subscription requests and held messages.
"""

from munepy import Enum
from zope.interface import Interface, Attribute



class RequestType(Enum):
    held_message = 1
    subscription = 2
    unsubscription = 3



class IListRequests(Interface):
    """Held requests for a specific mailing list."""

    mailing_list = Attribute(
        """The IMailingList for these requests.""")

    count = Attribute(
        """The total number of requests held for the mailing list.""")

    def hold_request(request_type, key, data=None):
        """Hold some data for moderator approval.

        :param request_type: A `Request` enum value.
        :param key: The key piece of request data being held.
        :param data: Additional optional data in the form of a dictionary that
            is associated with the held request.
        :return: A unique id for this held request.
        """

    held_requests = Attribute(
        """An iterator over the held requests, yielding a 2-tuple.

        The tuple has the form: (id, type) where `id` is the held request's
        unique id and the `type` is a `Request` enum value.
        """)

    def get_request(request_id):
        """Get the data associated with the request id, or None.

        :param request_id: The unique id for the request.
        :return: A 2-tuple of the key and data originally held, or None if the
            `request_id` is not in the database.
        """

    def delete_request(request_id):
        """Delete the request associated with the id.

        :param request_id: The unique id for the request.
        :raises KeyError: If `request_id` is not in the database.
        """



class IRequests(Interface):
    """The requests database."""

    def get_list_requests(mailing_list):
        """Return the `IListRequests` object for the given mailing list.

        :param mailing_list: An `IMailingList`.
        :return: An `IListRequests` object for the mailing list.
        """
