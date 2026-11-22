import math


class PhysicsLab:
    MAX_TIME_STEPS = 100_000

    def __init__(self, gravity=9.81):
        if (isinstance(gravity, bool) or not isinstance(gravity, (int, float))
                or not math.isfinite(gravity) or gravity <= 0):
            raise ValueError("Gravidade deve ser positiva e finita.")

        self.gravity = float(gravity)

    def free_fall(self, initial_height, initial_velocity=0, duration=1, step=0.1):

        values = (initial_height, initial_velocity, duration, step)

        if any(
            isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v)
            for v in values
        ):
            raise ValueError("Todos os parametros devem ser numeros finitos.")

        if initial_height <= 0 or step <= 0 or duration < 0:
            raise ValueError("Parametros invalidos.")

        estimated_steps = duration / step
        if not math.isfinite(estimated_steps) or estimated_steps >= self.MAX_TIME_STEPS:
            raise ValueError("Simulacao excede o limite maximo de passos.")

        g = self.gravity
        discriminant = initial_velocity * initial_velocity + 2 * g * initial_height
        if not math.isfinite(discriminant) or discriminant <= 0:
            raise ValueError("Estado inicial excede o dominio numerico suportado.")

        root = math.sqrt(discriminant)
        if initial_velocity < 0:
            impact_time = (2 * initial_height) / (root - initial_velocity)
        else:
            impact_time = (initial_velocity + root) / g
        if not math.isfinite(impact_time) or impact_time <= 0:
            raise ValueError("Tempo de impacto fora do dominio numerico suportado.")

        results = []
        apex_time = initial_velocity / g if initial_velocity > 0 else None
        apex_height = (
            initial_height + (initial_velocity * initial_velocity) / (2 * g)
            if apex_time is not None else None
        )
        if apex_height is not None and not math.isfinite(apex_height):
            raise ValueError("Altura maxima fora do dominio numerico suportado.")
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


