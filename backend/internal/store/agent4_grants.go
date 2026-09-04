package store

// agent4ReadGrant is intentionally not caller-supplied. A4-16 exposes one
// fixed capability only; it is not a general RBAC or arbitrary-scope API.
const agent4ReadGrant = "agent4:read"

// SetAgent4ReadGrant atomically adds or removes the fixed Agent 4 read grant on
// one paired device. It is idempotent and fails closed: persistence failure
// restores the exact previous in-memory grant slice before returning an error.
//
// Returns the resulting device, whether the device exists, whether durable
// state changed, and any persistence error.
func (s *Store) SetAgent4ReadGrant(
	deviceID string,
	enabled bool,
) (Device, bool, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	for i := range s.d.Devices {
		if s.d.Devices[i].ID != deviceID {
			continue
		}

		oldGrants := append([]string(nil), s.d.Devices[i].Grants...)
		hadGrant := false
		for _, grant := range oldGrants {
			if grant == agent4ReadGrant {
				hadGrant = true
				break
			}
		}

		if enabled == hadGrant {
			return cloneDevice(s.d.Devices[i]), true, false, nil
		}

		if enabled {
			s.d.Devices[i].Grants = append(oldGrants, agent4ReadGrant)
		} else {
			next := make([]string, 0, len(oldGrants))
			for _, grant := range oldGrants {
				if grant != agent4ReadGrant {
					next = append(next, grant)
				}
			}
			s.d.Devices[i].Grants = next
		}

		if err := s.persistLocked(); err != nil {
			s.d.Devices[i].Grants = oldGrants
			return Device{}, true, false, err
		}
		return cloneDevice(s.d.Devices[i]), true, true, nil
	}

	return Device{}, false, false, nil
}

func cloneDevice(device Device) Device {
	device.Grants = append([]string(nil), device.Grants...)
	return device
}
