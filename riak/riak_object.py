import types, copy
from metadata import *


class RiakObject(object):
    """
    The RiakObject holds meta information about a Riak object, plus the
    object's data.
    """
    def __init__(self, client, bucket, key=None):
        """
        Construct a new RiakObject.
        @param RiakClient client - A RiakClient object.
        @param RiakBucket bucket - A RiakBucket object.
        @param string key - An optional key. If not specified, then key
        is generated by server when store(...) is called.
        """
        self._client = client
        self._bucket = bucket
        self._key = key
        self._encode_data = True
        self._vclock = None
        self._data = None
        self._metadata = {}
        self._links = []
        self._siblings = []
        self._exists = False

    def get_bucket(self):
        """
        Get the bucket of this object.
        @return RiakBucket
        """
        return self._bucket;

    def get_key(self):
        """
        Get the key of this object.
        @return string
        """
        return self._key


    def get_data(self):
        """
        Get the data stored in this object. Will return a associative
        array, unless the object was constructed with new_binary(...) or
        get_binary(...), in which case this will return a string.
        @return array or string
        """
        return self._data

    def set_data(self, data):
        """
        Set the data stored in this object. This data will be
        JSON encoded unless the object was constructed with
        new_binary(...) or get_binary(...).
        @param mixed data - The data to store.
        @return data
        """
        self._data = data
        return self

    def get_encoded_data(self):
        """
        Get the data encoded for storing
        """
        if self._encode_data == True:
            content_type = self.get_content_type()
            encoder = self._bucket.get_encoder(content_type)
            if encoder == None:
                if isinstance(self._data, basestring):
                    return self._data.encode()
                else:
                    raise RiakError("No encoder for non-string data "
                                    "with content type ${0}".
                                    format(content_type))
            else:
                return encoder(self._data)
        else:
            return self._data

    def set_encoded_data(self, data):
        """
        Set the object data from an encoded string - make sure
        the metadata has been set correctly first.
        """
        if self._encode_data == True:
            content_type = self.get_content_type()
            decoder = self._bucket.get_decoder(content_type)
            if decoder == None:
                # if no decoder, just set as string data for application to handle
                self._data = data
            else:
                self._data = decoder(data)
        else:
            self._data = data
        return self


    def get_metadata(self):
        """
        Get the metadata stored in this object. Will return a associative
        array
        @return dict
        """
        return self._metadata

    def set_metadata(self, metadata):
        """
        Set the metadata stored in this object.
        @param dict metadata - The data to store.
        @return data
        """
        self._metadata = metadata
        return self

    def exists(self):
        """
        Return True if the object exists, False otherwise. Allows you to
        detect a get(...) or get_binary(...) operation where the object is missing.
        @return boolean
        """
        return self._exists

    def get_content_type(self):
        """
        Get the content type of this object. This is either application/json, or
        the provided content type if the object was created via new_binary(...).
        @return string
        """
        return self._metadata[MD_CTYPE]

    def set_content_type(self, content_type):
        """
        Set the content type of this object.
        @param string content_type - The new content type.
        @return self
        """
        self._metadata[MD_CTYPE] = content_type
        return self

    def add_link(self, obj, tag=None):
        """
        Add a link to a RiakObject.
        @param mixed obj - Either a RiakObject or a RiakLink object.
        @param string tag - Optional link tag. (default is bucket name,
        ignored if obj is a RiakLink object.)
        @return RiakObject
        """
        if isinstance(obj, RiakLink):
            newlink = obj
        else:
            newlink = RiakLink(obj._bucket._name, obj._key, tag)

        self.remove_link(newlink)
        links = self._metadata[MD_LINKS]
        links.append(newlink)
        return self

    def remove_link(self, obj, tag=None):
        """
        Remove a link to a RiakObject.
        @param mixed obj - Either a RiakObject or a RiakLink object.
        @param string tag -
        @param mixed obj - Either a RiakObject or a RiakLink object.
        @param string tag - Optional link tag. (default is bucket name,
        ignored if obj is a RiakLink object.)
        @return self
        """
        if isinstance(obj, RiakLink):
            oldlink = obj
        else:
            oldlink = RiakLink(obj._bucket._name, obj._key, tag)

        a = []
        links = self._metadata.get(MD_LINKS, [])
        for link in links:
            if not link.isEqual(oldlink):
                a.append(link)

        self._metadata[MD_LINKS] = a
        return self

    def get_links(self):
        """
        Return an array of RiakLink objects.
        @return array()
        """
        # Set the clients before returning...
        if MD_LINKS in self._metadata:
            links = self._metadata[MD_LINKS]
            for link in links:
                link._client = self._client
            return links
        else:
            return []

    def store(self, w=None, dw=None, return_body=True):
        """
        Store the object in Riak. When this operation completes, the
        object could contain new metadata and possibly new data if Riak
        contains a newer version of the object according to the object's
        vector clock.
        @param integer w - W-value, wait for this many partitions to respond
        before returning to client.
        @param integer dw - DW-value, wait for this many partitions to
        confirm the write before returning to client.
        @param bool return_body - if the newly stored object should be retrieved
        @return self
        """
        # Use defaults if not specified...
        w = self._bucket.get_w(w)
        dw = self._bucket.get_dw(w)

        # Issue the get over our transport
        t = self._client.get_transport()
        Result = t.put(self, w, dw, return_body)
        if Result is not None:
            self.populate(Result)

        return self


    def reload(self, r=None, vtag=None):
        """
        Reload the object from Riak. When this operation completes, the
        object could contain new metadata and a new value, if the object
        was updated in Riak since it was last retrieved.
        @param integer r - R-Value, wait for this many partitions to respond
        before returning to client.
        @return self
        """
        # Do the request...
        r = self._bucket.get_r(r)
        t = self._client.get_transport()
        Result = t.get(self, r, vtag)

        self.clear()
        if Result is not None:
            self.populate(Result)

        return self


    def delete(self, rw=None):
        """
        Delete this object from Riak.
        @param integer rw - RW-value. Wait until this many partitions have
        deleted the object before responding.
        @return self
        """
        # Use defaults if not specified...
        rw = self._bucket.get_rw(rw)
        t = self._client.get_transport()
        Result = t.delete(self, rw)
        self.clear()
        return self

    def clear(self) :
        """
        Reset this object.
        @return self
        """
        self._headers = []
        self._links = []
        self._data = None
        self._exists = False
        self._siblings = []
        return self

    def vclock(self) :
        """
        Get the vclock of this object.
        @return string
        """
        return self._vclock

    def populate(self, Result) :
        """
        Populate the object based on the return from get.
        If None returned, then object is not found
        If a tuple of vclock, contents then one or more
        whole revisions of the key were found
        If a list of vtags is returned there are multiple
        sibling that need to be retrieved with get.
        """
        self.clear()
        if Result == None:
            return self
        elif type(Result) == types.ListType:
            self.set_siblings(Result)
        elif type(Result) == types.TupleType:
            (vclock, contents) = Result
            self._vclock = vclock
            if len(contents) > 0:
                (metadata, data) = contents.pop(0)
                self._exists = True
                self.set_metadata(metadata)
                self.set_encoded_data(data)
                # Create objects for all siblings
                siblings = [self]
                for (metadata, data) in contents:
                    sibling = copy.copy(self)
                    sibling.set_metadata(metadata)
                    sibling.set_encoded_data(data)
                    siblings.append(sibling)
                for sibling in siblings:
                    sibling.set_siblings(siblings)
        else:
            raise RiakError("do not know how to handle type " + str(type(Result)))

    def populate_links(self, linkHeaders) :
        """
        Private.
        @return self
        """
        for linkHeader in linkHeaders.strip().split(','):
            linkHeader = linkHeader.strip()
            matches = re.match("\<\/([^\/]+)\/([^\/]+)\/([^\/]+)\>; ?riaktag=\"([^\']+)\"", linkHeader)
            if (matches is not None):
                link = RiakLink(matches.group(2), matches.group(3), matches.group(4))
                self._links.append(link)
        return self

    def has_siblings(self):
        """
        Return True if this object has siblings.
        @return boolean
        """
        return(self.get_sibling_count() > 0)

    def get_sibling_count(self):
        """
        Get the number of siblings that this object contains.
        @return integer
        """
        return len(self._siblings)

    def get_sibling(self, i, r=None):
        """
        Retrieve a sibling by sibling number.
        @param  integer i - Sibling number.
        @param  integer r - R-Value. Wait until this many partitions
        have responded before returning to client.
        @return RiakObject.
        """
        if isinstance(self._siblings[i], RiakObject):
            return self._siblings[i]
        else:
            # Use defaults if not specified.
            r = self._bucket.get_r(r)

            # Run the request...
            vtag = self._siblings[i]
            obj = RiakObject(self._client, self._bucket, self._key)
            obj.reload(r, vtag)

            # And make sure it knows who it's siblings are
            self._siblings[i] = obj
            obj.set_siblings(self._siblings)
            return obj

    def get_siblings(self, r=None):
        """
        Retrieve an array of siblings.
        @param integer r - R-Value. Wait until this many partitions have
        responded before returning to client.
        @return array of RiakObject
        """
        a = [self]
        for i in range(self.get_sibling_count()):
            a.append(self.get_sibling(i, r))
        return a

    def set_siblings(self, siblings):
        """
        Set the array of siblings - used internally
        Make sure this object is at index 0 so get_siblings(0) always returns
        the current object
        """
        try:
            i = siblings.index(self)
            if i != 0:
                siblings.pop(i)
                siblings.insert(0, self)
        except ValueError:
            pass

        if len(siblings) > 1:
            self._siblings = siblings
        else:
            self._siblings = []

    def add(self, *args):
        """
        Start assembling a Map/Reduce operation.
        @see RiakMapReduce.add()
        @return RiakMapReduce
        """
        mr = RiakMapReduce(self._client)
        mr.add(self._bucket._name, self._key)
        return apply(mr.add, args)

    def link(self, *args):
        """
        Start assembling a Map/Reduce operation.
        @see RiakMapReduce.link()
        @return RiakMapReduce
        """
        mr = RiakMapReduce(self._client)
        mr.add(self._bucket._name, self._key)
        return apply(mr.link, args)

    def map(self, *args):
        """
        Start assembling a Map/Reduce operation.
        @see RiakMapReduce.map()
        @return RiakMapReduce
        """
        mr = RiakMapReduce(self._client)
        mr.add(self._bucket._name, self._key)
        return apply(mr.map, args)

    def reduce(self, params):
        """
        Start assembling a Map/Reduce operation.
        @see RiakMapReduce.reduce()
        @return RiakMapReduce
        """
        mr = RiakMapReduce(self._client)
        mr.add(self._bucket._name, self._key)
        return apply(mr.reduce, args)

from mapreduce import *
