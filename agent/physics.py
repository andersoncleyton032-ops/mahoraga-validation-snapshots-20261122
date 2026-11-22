import math


class PhysicsLab:
    def __init__(self, gravity=9.81):
        if not isinstance(gravity, (int, float)) or not math.isfinite(gravity) or gravity <= 0:
            raise ValueError("Gravidade deve ser positiva e finita.")

        self.gravity = gravity

    def free_fall(self, initial_height, initial_velocity=0, duration=1, step=0.1):

        values = (initial_height, initial_velocity, duration, step)

        if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError("Todos os parametros devem ser numeros finitos.")

        if initial_height <= 0 or step <= 0 or duration < 0:
            raise ValueError("Parametros invalidos.")

        g = self.gravity
        discriminant = initial_velocity**2 + 2 * g * initial_height
        impact_time = (initial_velocity + math.sqrt(discriminant)) / g

        results = []
        apex_time = initial_velocity / g if initial_velocity > 0 else None
        apex_height = initial_height + initial_velocity**2 / (2 * g) if apex_time is not None else None
        time = 0.0

        while time <= duration:

            if time >= impact_time:
                results.append({
                    "time": impact_time,
                    "position": 0,
                    "velocity": initial_velocity - g * impact_time,
                    "impact": True
                })
                break

            position = (
                initial_height
                + initial_velocity * time
                - 0.5 * g * time**2
            )

            velocity = initial_velocity - g * time

            results.append({
                "time": round(time, 6),
                "position": round(position, 6),
                "velocity": round(velocity, 6),
                "impact": False
            })

            next_time = round(time + step, 10)

            if apex_time is not None and time < apex_time <= next_time and apex_time <= duration and apex_time < impact_time:
                results.append({
                    "time": apex_time,
                    "position": apex_height,
                    "velocity": 0,
                    "impact": False,
                    "apex": True
                })

            if impact_time < next_time and impact_time <= duration:
                results.append({
                    "time": impact_time,
                    "position": 0,
                    "velocity": initial_velocity - g * impact_time,
                    "impact": True
                })
                break

            time = next_time

        return results


